"""The coordinator: fetches Jelu data on a schedule and makes changes on request.

A DataUpdateCoordinator is HA's standard way to poll an API once and share the result. Every
SCAN_INTERVAL it calls _async_update_data(), stores the result in `self.data`, and tells every
subscribed entity to redraw. If a poll fails, the entities show as unavailable until one works.

Writes (progress, finish, drop) also go through here, so the to-do list and the actions handle
errors the same way and both refresh the data straight afterwards.
"""

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import date
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .api import (
    JeluAuthenticationError,
    JeluClient,
    JeluError,
    JeluPermissionError,
    ReadingEvent,
    ReadingEventType,
)
from .const import DOMAIN, MAX_CURRENTLY_READING, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

# A config entry whose runtime_data is our coordinator (set in __init__.py). Using this alias
# instead of plain ConfigEntry lets the type checker know what entry.runtime_data holds.
type JeluConfigEntry = ConfigEntry[JeluDataUpdateCoordinator]


@dataclass(frozen=True, slots=True)
class JeluData:
    """Everything one poll fetches. Entities read their values from this."""

    app_version: str  # Jelu's version, shown on the device page
    currently_reading: list[
        ReadingEvent
    ]  # books in progress, up to MAX_CURRENTLY_READING
    currently_reading_total: int  # how many books are in progress, even past the cap
    finished_this_year: int
    finished_total: int


class JeluDataUpdateCoordinator(DataUpdateCoordinator[JeluData]):
    """Polls one Jelu server and makes changes to it."""

    config_entry: JeluConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: JeluConfigEntry, client: JeluClient
    ) -> None:
        """Set up the coordinator. Nothing is fetched until the first refresh."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> JeluData:
        """Fetch the latest data from Jelu. HA calls this on every poll.

        Jelu has a /stats endpoint, but API tokens can't call it (see api.py), so the counts
        come from the reading-events list instead: asking for one item also returns the total
        number of matching events, and that total is the count.
        """
        # Jelu counts endedAfter from midnight (server time) on that date, inclusive.
        year_start = date(dt_util.now().year, 1, 1)
        try:
            # Send the four requests at the same time rather than one after another.
            info, reading, finished_this_year, finished_total = await asyncio.gather(
                self.client.async_get_server_info(),
                self.client.async_get_reading_events(
                    [ReadingEventType.CURRENTLY_READING], size=MAX_CURRENTLY_READING
                ),
                self.client.async_count_reading_events(
                    [ReadingEventType.FINISHED], ended_after=year_start
                ),
                self.client.async_count_reading_events([ReadingEventType.FINISHED]),
            )
        # The coordinator recognises these two exceptions:
        except (JeluAuthenticationError, JeluPermissionError) as err:
            # The token was rejected or lost its scope: HA prompts the user for a new one.
            raise ConfigEntryAuthFailed(str(err)) from err
        except JeluError as err:
            # Anything else (server down, timeout, odd reply): entities become unavailable
            # and the next scheduled poll tries again.
            raise UpdateFailed(str(err)) from err

        return JeluData(
            app_version=info.app_version,
            currently_reading=reading.events,
            currently_reading_total=reading.total,
            finished_this_year=finished_this_year,
            finished_total=finished_total,
        )

    def find_book(self, query: str) -> ReadingEvent:
        """Find a book being read from what the user typed in an action.

        Tries, in order: the exact title (any case) or a Jelu ID, then part of a title.
        Raises ServiceValidationError, shown to the user, if nothing or more than one book
        matches. Only books currently being read are searched.
        """
        books = self.data.currently_reading
        wanted = (
            query.strip().casefold()
        )  # casefold() is lower() that also handles e.g. "ß"
        for book in books:
            if wanted in (
                book.title.casefold(),
                book.book_id.casefold(),
                book.user_book_id.casefold(),
            ):
                return book
        matches = [book for book in books if wanted in book.title.casefold()]
        if len(matches) == 1:
            return matches[0]
        # The message text lives in translations/en.json under "exceptions", looked up by
        # translation_key; the placeholders fill in its {book} and {books} parts.
        if not matches:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="book_not_found",
                translation_placeholders={
                    "book": query,
                    "books": _titles(books) or "none",
                },
            )
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="book_ambiguous",
            translation_placeholders={"book": query, "books": _titles(matches)},
        )

    async def async_set_progress(
        self, book: ReadingEvent, *, page: int | None, percent: int | None
    ) -> None:
        """Set a book's progress in Jelu (give a page or a percent), then refresh."""
        await self._async_write(
            self.client.async_set_progress(
                book.user_book_id, page=page, percent=percent
            )
        )

    async def async_set_reading_status(
        self, book: ReadingEvent, event_type: ReadingEventType
    ) -> None:
        """Mark a book finished or dropped in Jelu, then refresh."""
        await self._async_write(
            self.client.async_set_reading_status(book.book_id, event_type)
        )

    async def _async_write(self, request: Awaitable[None]) -> None:
        """Run a write request, turning client errors into messages for the user.

        `request` is the not-yet-awaited client call, so this one place handles errors for
        every kind of write. HomeAssistantError is what HA shows in the UI when an action or
        a to-do change fails.
        """
        try:
            await request
        except JeluPermissionError as err:
            # The token is fine for reading but lacks the reading:write scope.
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="missing_write_scope"
            ) from err
        except JeluAuthenticationError as err:
            # The token was revoked or expired: ask the user for a new one, as polling would.
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except JeluError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
        # Fetch fresh data now, so the change shows up without waiting for the next poll
        # (a finished book leaves the to-do list, the counts go up, and so on).
        await self.async_request_refresh()


def _titles(books: list[ReadingEvent]) -> str:
    """Join book titles for an error message, e.g. "Dune, Kindred"."""
    return ", ".join(book.title for book in books)
