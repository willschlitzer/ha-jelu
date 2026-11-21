"""Data update coordinator for the Jelu integration."""

import asyncio
from dataclasses import dataclass
from datetime import date
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
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
