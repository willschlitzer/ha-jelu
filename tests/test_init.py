"""Tests for setting up the Jelu integration."""

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
    """A rejected token fails setup and asks the user to re-authenticate."""
    aioclient_mock.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    aioclient_mock.get(f"{API}/reading-events/me", status=status)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
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
    await hass.async_block_till_done()
    calls = mock_jelu.call_count

    async_fire_time_changed(
        hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1)
    )
    await hass.async_block_till_done()
    assert mock_jelu.call_count == calls * 2
