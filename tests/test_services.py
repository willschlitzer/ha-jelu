"""Tests for the Jelu actions."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .conftest import API
from custom_components.jelu.const import DOMAIN


@pytest.fixture(autouse=True)
def _frozen_time(freezer: FrozenDateTimeFactory) -> None:
    """Fix "this year" to 2026, to match the mocked queries."""
    freezer.move_to("2026-11-20 12:00:00+00:00")


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant,
    mock_library: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the integration with "Dune" and "Kindred" being read."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


def _writes(mock: AiohttpClientMocker) -> list[tuple[str, str, object]]:
    return [
        (method, url.path, data)
        for method, url, data, _ in mock.mock_calls
        if method in ("PUT", "POST")
    ]


@pytest.mark.parametrize(
    ("data", "body"),
    [
        ({"page": 300}, {"currentPageNumber": 300, "percentRead": None}),
        ({"percent": 50}, {"currentPageNumber": None, "percentRead": 50}),
    ],
)
async def test_set_progress(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_library: AiohttpClientMocker,
    data: dict,
    body: dict,
) -> None:
    """Progress is sent for the matching book (partial, any-case title)."""
    mock_library.put(f"{API}/userbooks/userbook-Dune", json={})
    await hass.services.async_call(
        DOMAIN, "set_progress", {"book": "dun", **data}, blocking=True
    )
    assert _writes(mock_library) == [("PUT", "/api/v1/userbooks/userbook-Dune", body)]


@pytest.mark.parametrize(
    ("service", "event_type"), [("finish_book", "FINISHED"), ("drop_book", "DROPPED")]
)
async def test_finish_and_drop(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_library: AiohttpClientMocker,
    service: str,
    event_type: str,
) -> None:
    """Finishing or dropping posts the event for the book, for the given entry."""
    mock_library.post(f"{API}/reading-events", json={})
    await hass.services.async_call(
        DOMAIN,
        service,
        {ATTR_CONFIG_ENTRY_ID: setup_entry.entry_id, "book": "Kindred"},
        blocking=True,
    )
    assert _writes(mock_library) == [
        (
            "POST",
            "/api/v1/reading-events",
            {"eventType": event_type, "bookId": "book-Kindred"},
        )
    ]


@pytest.mark.parametrize(
    ("data", "translation_key"),
    [
        ({"book": "Dune"}, "page_or_percent"),
        ({"book": "Dune", "page": 1, "percent": 1}, "page_or_percent"),
        ({"book": "Piranesi", "page": 1}, "book_not_found"),
        ({"book": "n", "page": 1}, "book_ambiguous"),
    ],
)
async def test_set_progress_invalid(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_library: AiohttpClientMocker,
    data: dict,
    translation_key: str,
) -> None:
    """Bad input is rejected before anything is sent to Jelu."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "set_progress", data, blocking=True)
    assert err.value.translation_key == translation_key
    assert _writes(mock_library) == []


async def test_percent_out_of_range(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Percent must be 0-100."""
    with pytest.raises(Exception, match="value must be at most 100"):
        await hass.services.async_call(
            DOMAIN, "set_progress", {"book": "Dune", "percent": 101}, blocking=True
        )


async def test_rejected_token_starts_reauth(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_library: AiohttpClientMocker,
) -> None:
    """A revoked token fails the action and asks for a new one."""
    mock_library.post(f"{API}/reading-events", status=401)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "finish_book", {"book": "Dune"}, blocking=True
        )
    assert err.value.translation_key == "auth_failed"
    await hass.async_block_till_done()
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH
