"""Actions: jelu.set_progress, jelu.finish_book and jelu.drop_book.

("Actions" is HA's current name for what the code still calls "services".)

Three files describe each action:
  - this file: what it does, and a schema that validates its input;
  - services.yaml: its fields and the input widget for each, used by HA's action editor;
  - translations/en.json, under "services": the action and field names and descriptions.

Every action takes a `book` (a title, or part of one) and an optional config entry ID (which
Jelu server, needed only if there's more than one). The coordinator does the real work.
"""

import probatio

from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service

from .api import ReadingEventType
from .const import DOMAIN
from .coordinator import JeluConfigEntry

# Field names, as written in automations (e.g. `data: {book: Dune, page: 120}`).
ATTR_BOOK = "book"
ATTR_PAGE = "page"
ATTR_PERCENT = "percent"

# Action names (the part after "jelu.").
SERVICE_SET_PROGRESS = "set_progress"
SERVICE_FINISH_BOOK = "finish_book"
SERVICE_DROP_BOOK = "drop_book"

# The fields every action takes. HA checks a call against its schema before calling the
# handler, so the handlers can trust the types (e.g. that page is an int ≥ 0).
BOOK_SCHEMA = {
    # Optional: with only one Jelu server configured, that one is used.
    probatio.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    probatio.Required(ATTR_BOOK): cv.string,
}

SET_PROGRESS_SCHEMA = probatio.Schema(
    {
        **BOOK_SCHEMA,
        # Both optional here; "exactly one of the two" is checked in the handler, so the
        # error message can say so plainly.
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
    """Find the config entry the call is for.

    HA's helper raises a clear error if the entry doesn't exist, isn't Jelu, or isn't
    loaded. Given no ID, it uses the only loaded Jelu entry (or errors if there are several).
    """
    return service.async_get_config_entry(
        hass, DOMAIN, call.data.get(ATTR_CONFIG_ENTRY_ID)
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Jelu actions. Called once from async_setup in __init__.py.

    Each handler follows the same pattern: find the server, find the book (both raise a
    user-facing error if they can't), then ask the coordinator to make the change.
    """

    async def async_set_progress(call: ServiceCall) -> None:
        """Set how far through a book the reader is, as a page or a percentage."""
        page = call.data.get(ATTR_PAGE)
        percent = call.data.get(ATTR_PERCENT)
        if (page is None) == (percent is None):  # both given, or neither
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
