"""Tests for the sensors (sensor.py).

Most tests set up the integration against mock_library (conftest.py), then read the sensors'
states from hass.states, which is what a dashboard or automation would see.
"""

from aiohttp import ClientError
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import API, SERVER_SETTINGS, register_library
from custom_components.jelu.const import DOMAIN


@pytest.fixture(autouse=True)
def _frozen_time(freezer: FrozenDateTimeFactory) -> None:
    """Fix "this year" to 2026.

    mock_library answers the "finished this year" query only for endedAfter=2026-01-01, so
    the clock must say 2026 whenever the tests run. autouse: applies to every test here.
    """
    freezer.move_to("2026-11-20 12:00:00+00:00")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry to HA, set it up, and wait until its entities exist."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_sensors(
    hass: HomeAssistant,
    mock_library: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Each sensor shows its count, with the in-progress books as an attribute."""
    await _setup(hass, config_entry)

    # States are strings, and units and state classes are attributes, as HA stores them.
    reading = hass.states.get("sensor.jelu_currently_reading")
    assert reading is not None
    assert reading.state == "2"
    assert reading.attributes["unit_of_measurement"] == "books"
    assert reading.attributes["state_class"] == "measurement"
    assert reading.attributes["books"] == [
        {
            "title": "Dune",
            "authors": ["Ursula K. Le Guin"],
            "started": "2026-11-01",
            "percent": 45,
        },
        {
            "title": "Kindred",
            "authors": ["Ursula K. Le Guin"],
            "started": "2026-11-01",
            "percent": None,
        },
    ]

    this_year = hass.states.get("sensor.jelu_finished_this_year")
    assert this_year is not None
    assert this_year.state == "12"
    assert this_year.attributes["state_class"] == "total_increasing"
    assert "books" not in this_year.attributes

    total = hass.states.get("sensor.jelu_finished_total")
    assert total is not None
    assert total.state == "87"


async def test_device_and_unique_ids(
    hass: HomeAssistant,
    mock_library: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """All entities belong to one service device that links to the Jelu server.

    device_registry and entity_registry are HA's stored records of devices and entities
    (what the Devices and Entities pages list), provided as fixtures.
    """
    await _setup(hass, config_entry)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, config_entry.entry_id), config_entry.entry_id
    )
    assert device is not None
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.sw_version == "0.88.4"
    assert device.configuration_url == "https://jelu.example.com"

    entities = er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)
    assert {entity.unique_id for entity in entities} == {
        f"{config_entry.entry_id}_currently_reading",
        f"{config_entry.entry_id}_finished_this_year",
        f"{config_entry.entry_id}_finished_total",
        f"{config_entry.entry_id}_currently_reading_todo",
    }
    assert all(entity.device_id == device.id for entity in entities)


async def test_books_attribute_not_recorded(
    hass: HomeAssistant,
    mock_library: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The book list is excluded from the recorder (HA's history database).

    There's no public way to ask an entity which attributes it leaves out, so this looks up
    the entity object itself and checks the private setting directly.
    """
    await _setup(hass, config_entry)
    entity = hass.data["entity_components"]["sensor"].get_entity(
        "sensor.jelu_currently_reading"
    )
    assert "books" in entity._unrecorded_attributes  # noqa: SLF001


async def test_unavailable_when_server_fails(
    hass: HomeAssistant,
    mock_library: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Sensors go unavailable when Jelu can't be reached, and recover when it's back."""
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data

    # Make the server unreachable, then poll now. (Calling the coordinator's refresh
    # directly avoids waiting for, or faking, the 5-minute poll timer.)
    mock_library.clear_requests()
    mock_library.get(f"{API}/server-settings", exc=ClientError())
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.jelu_finished_total")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    # The server comes back, now reporting one more finished book. The next poll should
    # bring the sensor back with the new value: 88, not the 87 it showed before.
    mock_library.clear_requests()
    register_library(mock_library, finished_total=88)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.jelu_finished_total")
    assert state is not None
    assert state.state == "88"


async def test_rejected_token_during_update_starts_reauth(
    hass: HomeAssistant,
    mock_library: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A token revoked after setup prompts the user for a new one."""
    await _setup(hass, config_entry)

    # The token stops working: settings still load (no token needed), the rest gets 401.
    mock_library.clear_requests()
    mock_library.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    mock_library.get(f"{API}/reading-events/me", status=401)
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # Exactly one flow is in progress, and it's a reauth (the "enter a new token" dialog).
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH
