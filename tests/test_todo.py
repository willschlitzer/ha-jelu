"""Tests for the "Currently reading" to-do list (todo.py).

The to-do list is used through HA's own todo actions, as the to-do card and Assist use it:
todo.get_items to read the items, and todo.update_item to change one (checking it off sends
status "completed"). The tests set up the integration with "Dune" and "Kindred" being read
(mock_library in conftest.py).
"""

from typing import Any, cast

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .conftest import API

ENTITY_ID = "todo.jelu_currently_reading"


@pytest.fixture(autouse=True)
def _frozen_time(freezer: FrozenDateTimeFactory) -> None:
    """Fix "this year" to 2026, to match the mocked queries.

    mock_library answers the "finished this year" query only for endedAfter=2026-01-01, so
    the clock must say 2026 whenever the tests run. autouse: applies to every test here.
    """
    freezer.move_to("2026-11-20 12:00:00+00:00")


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant,
    mock_library: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the integration with two books being read."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def _get_items(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Read the list's items through HA's todo.get_items action."""
    result = await hass.services.async_call(
        TODO_DOMAIN,
        "get_items",
        {},
        target={ATTR_ENTITY_ID: ENTITY_ID},
        blocking=True,
        return_response=True,
    )
    # Service responses are typed as any JSON value; this one is {entity_id: {"items": [...]}}.
    response = cast(dict[str, dict[str, list[dict[str, Any]]]], result)
    return response[ENTITY_ID]["items"]


async def test_items(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """Each book being read is an open item, with authors and progress as the description."""
    # A to-do list's state is its number of open items.
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "2"
    assert await _get_items(hass) == [
        {
            "uid": "userbook-Dune",
            "summary": "Dune",
            "description": "Ursula K. Le Guin · 45% (page 270 of 600)",
            "status": "needs_action",
        },
        {
            "uid": "userbook-Kindred",
            "summary": "Kindred",
            "description": "Ursula K. Le Guin",
            "status": "needs_action",
        },
    ]


async def test_check_off_finishes_book(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_library: AiohttpClientMocker,
) -> None:
    """Checking a book off marks it finished in Jelu, then refreshes."""
    mock_library.post(f"{API}/reading-events", json={})
    calls_before = mock_library.call_count

    # The item is picked by its summary (the title), as Assist would.
    await hass.services.async_call(
        TODO_DOMAIN,
        "update_item",
        {"item": "Dune", "status": "completed"},
        target={ATTR_ENTITY_ID: ENTITY_ID},
        blocking=True,
    )

    # One POST was sent, with this body (call[0] is the method, call[2] the body).
    writes = [call for call in mock_library.mock_calls if call[0] == "POST"]
    assert [call[2] for call in writes] == [
        {"eventType": "FINISHED", "bookId": "book-Dune"}
    ]
    # A refresh followed the write: more requests than just the one POST.
    assert mock_library.call_count > calls_before + 1


async def test_rename_rejected(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Only checking off is supported; renaming is refused with an explanation."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            TODO_DOMAIN,
            "update_item",
            {"item": "Dune", "rename": "Dune Messiah"},
            target={ATTR_ENTITY_ID: ENTITY_ID},
            blocking=True,
        )
    assert err.value.translation_key == "todo_only_complete"


async def test_check_off_without_write_scope(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_library: AiohttpClientMocker,
) -> None:
    """A read-only token gives a clear error."""
    mock_library.post(f"{API}/reading-events", status=403)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            TODO_DOMAIN,
            "update_item",
            {"item": "Dune", "status": "completed"},
            target={ATTR_ENTITY_ID: ENTITY_ID},
            blocking=True,
        )
    assert err.value.translation_key == "missing_write_scope"
