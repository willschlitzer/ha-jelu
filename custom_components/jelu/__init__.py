"""The Jelu integration."""

from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant

from .api import JeluClient
from .coordinator import JeluConfigEntry, JeluDataUpdateCoordinator
from .session import async_create_jelu_session

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: JeluConfigEntry) -> bool:
    """Set up Jelu from a config entry."""
    client = JeluClient(
        async_create_jelu_session(hass, entry.data[CONF_VERIFY_SSL]),
        entry.data[CONF_URL],
        entry.data[CONF_API_TOKEN],
    )
    coordinator = JeluDataUpdateCoordinator(hass, entry, client)
    # Raises ConfigEntryAuthFailed (starts reauth) or ConfigEntryNotReady (retries).
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JeluConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
