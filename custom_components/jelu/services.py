"""Actions for the Jelu integration."""

import probatio

from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service

from .api import ReadingEventType
from .const import DOMAIN
from .coordinator import JeluConfigEntry

ATTR_BOOK = "book"
ATTR_PAGE = "page"
ATTR_PERCENT = "percent"

SERVICE_SET_PROGRESS = "set_progress"
SERVICE_FINISH_BOOK = "finish_book"
SERVICE_DROP_BOOK = "drop_book"

BOOK_SCHEMA = {
    # Optional: with a single Jelu server configured, that one is used.
    probatio.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    probatio.Required(ATTR_BOOK): cv.string,
}

SET_PROGRESS_SCHEMA = probatio.Schema(
    {
        **BOOK_SCHEMA,
        probatio.Optional(ATTR_PAGE): probatio.All(
            probatio.Coerce(int), probatio.Range(min=0)
        ),
        probatio.Optional(ATTR_PERCENT): probatio.All(
            probatio.Coerce(int), probatio.Range(min=0, max=100)
        ),
    }
)

SET_STATUS_SCHEMA = probatio.Schema(BOOK_SCHEMA)


def _get_entry(hass: HomeAssistant, call: ServiceCall) -> JeluConfigEntry:
    return service.async_get_config_entry(
        hass, DOMAIN, call.data.get(ATTR_CONFIG_ENTRY_ID)
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Jelu actions."""

    async def async_set_progress(call: ServiceCall) -> None:
        """Set how far through a book the reader is."""
        page = call.data.get(ATTR_PAGE)
        percent = call.data.get(ATTR_PERCENT)
        if (page is None) == (percent is None):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="page_or_percent"
            )
        coordinator = _get_entry(hass, call).runtime_data
        book = coordinator.find_book(call.data[ATTR_BOOK])
        await coordinator.async_set_progress(book, page=page, percent=percent)

    async def async_finish_book(call: ServiceCall) -> None:
        """Mark a book finished."""
        coordinator = _get_entry(hass, call).runtime_data
        book = coordinator.find_book(call.data[ATTR_BOOK])
        await coordinator.async_set_reading_status(book, ReadingEventType.FINISHED)

    async def async_drop_book(call: ServiceCall) -> None:
        """Mark a book dropped."""
        coordinator = _get_entry(hass, call).runtime_data
        book = coordinator.find_book(call.data[ATTR_BOOK])
        await coordinator.async_set_reading_status(book, ReadingEventType.DROPPED)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_PROGRESS, async_set_progress, SET_PROGRESS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FINISH_BOOK, async_finish_book, SET_STATUS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DROP_BOOK, async_drop_book, SET_STATUS_SCHEMA
    )
