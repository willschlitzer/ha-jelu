"""Tests for setting up and unloading the integration (__init__.py).

Setting up an entry runs the coordinator's first poll. These tests check what HA does with
the result: entry loaded, setup error plus a reauth prompt (token rejected), or setup retry
(server unreachable). config_entry.state shows which happened.
"""

from datetime import timedelta

from aiohttp import ClientError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util

from .conftest import API, SERVER_SETTINGS
from custom_components.jelu.const import SCAN_INTERVAL


async def test_setup_and_unload(
    hass: HomeAssistant, mock_jelu: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """The entry loads with a working token and unloads cleanly."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize("status", [401, 403])
async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    status: int,
) -> None:
    """A rejected token fails setup and asks the user to re-authenticate.

    Runs for 401 (bad token) and 403 (token lacks the scope).
    """
    aioclient_mock.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    aioclient_mock.get(f"{API}/reading-events/me", status=status)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    # Exactly one flow is in progress, and it's a reauth (the "enter a new token" dialog).
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH


async def test_setup_unreachable_retries(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """An unreachable server makes Home Assistant retry later."""
    aioclient_mock.get(f"{API}/server-settings", exc=ClientError())
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_polls_on_interval(
    hass: HomeAssistant, mock_jelu: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """The coordinator polls Jelu again after the scan interval."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    # Wait for everything setup started to finish, then count the requests so far.
    await hass.async_block_till_done()
    calls = mock_jelu.call_count

    # Tell HA that time has jumped past the poll interval, so the scheduled poll runs.
    async_fire_time_changed(
        hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1)
    )
    await hass.async_block_till_done()
    # One more poll sends the same number of requests again.
    assert mock_jelu.call_count == calls * 2
