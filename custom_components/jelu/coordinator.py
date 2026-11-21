"""Data update coordinator for the Jelu integration."""

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

type JeluConfigEntry = ConfigEntry[JeluDataUpdateCoordinator]


@dataclass(frozen=True, slots=True)
class JeluData:
    """One snapshot of the reader's Jelu data."""

    app_version: str
    currently_reading: list[ReadingEvent]
    currently_reading_total: int
    finished_this_year: int
    finished_total: int


class JeluDataUpdateCoordinator(DataUpdateCoordinator[JeluData]):
    """Poll Jelu for reading progress.

    Tokens can't call /stats in Jelu 0.88.4, so each count is a one-item reading-events query
    whose page total is the count.
    """

    config_entry: JeluConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: JeluConfigEntry, client: JeluClient
    ) -> None:
        """Set up the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> JeluData:
        """Fetch the latest data from Jelu."""
        # Jelu applies endedAfter from midnight in the server's timezone, inclusive.
        year_start = date(dt_util.now().year, 1, 1)
        try:
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
        except (JeluAuthenticationError, JeluPermissionError) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except JeluError as err:
            raise UpdateFailed(str(err)) from err

        return JeluData(
            app_version=info.app_version,
            currently_reading=reading.events,
            currently_reading_total=reading.total,
            finished_this_year=finished_this_year,
            finished_total=finished_total,
        )

    def find_book(self, query: str) -> ReadingEvent:
        """Find a book being read by title (exact, then partial) or by Jelu ID.

        Raises ServiceValidationError if nothing or more than one book matches.
        """
        books = self.data.currently_reading
        wanted = query.strip().casefold()
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
        """Set a book's progress in Jelu, then refresh."""
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
        """Run a write request, turning client errors into Home Assistant errors."""
        try:
            await request
        except JeluPermissionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="missing_write_scope"
            ) from err
        except JeluAuthenticationError as err:
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
        await self.async_request_refresh()


def _titles(books: list[ReadingEvent]) -> str:
    return ", ".join(book.title for book in books)
