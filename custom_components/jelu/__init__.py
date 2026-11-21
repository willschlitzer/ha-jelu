"""The Jelu integration: Home Assistant's entry point.

How the pieces fit together (start here):

    config_flow.py   The setup dialog. Asks for the Jelu URL and an API token, checks them,
                     and saves them as a "config entry" (HA's stored record of one configured
                     instance of an integration).
          │
          ▼
    __init__.py      (this file) When HA starts, or a config entry is added, HA calls
                     async_setup_entry() below. It builds the API client and the coordinator,
                     then tells HA to load the entity platforms (sensor.py and todo.py).
          │
          ▼
    coordinator.py   Polls Jelu every few minutes and keeps the latest data in one place.
                     Entities read from it instead of each calling Jelu themselves. It also
                     carries out changes (progress, finish, drop) for the to-do list and actions.
          │
          ▼
    sensor.py        The count sensors (currently reading, finished this year, finished total).
    todo.py          The "currently reading" to-do list. Checking a book off finishes it.
    entity.py        Shared base class: puts every entity on one "Jelu" device.
    services.py      The jelu.set_progress / finish_book / drop_book actions.

    api.py           Plain async HTTP client for Jelu's REST API. Knows nothing about HA.
    session.py       The HTTP session the client uses (one that ignores cookies; see there).
    const.py         Shared constants.

Other files HA reads: manifest.json (metadata), services.yaml (action fields for the UI),
icons.json, translations/en.json (all user-facing text, looked up by key), brand/ (icons).
"""

from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import JeluClient
from .const import DOMAIN
from .coordinator import JeluConfigEntry, JeluDataUpdateCoordinator
from .services import async_setup_services
from .session import async_create_jelu_session

# The entity platforms this integration provides. For each one, HA imports the module of the
# same name (sensor.py, todo.py) and calls its async_setup_entry().
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.TODO]

# Jelu is set up through the UI only, not configuration.yaml. HA requires an integration that
# defines async_setup() to declare that.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Jelu actions.

    Called once when HA loads the integration, before any config entry is set up. Actions
    belong here rather than in async_setup_entry, so they exist (and give a clear error)
    even while no Jelu server is loaded, and aren't registered twice with two servers.
    """
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: JeluConfigEntry) -> bool:
    """Set up one configured Jelu server.

    `entry.data` holds what the config flow saved: the URL, the token and the SSL setting.
    """
    client = JeluClient(
        async_create_jelu_session(hass, entry.data[CONF_VERIFY_SSL]),
        entry.data[CONF_URL],
        entry.data[CONF_API_TOKEN],
    )
    coordinator = JeluDataUpdateCoordinator(hass, entry, client)

    # Fetch data once before creating any entities, so they start with real values.
    # If this fails, it raises one of two exceptions that HA handles for us:
    #   ConfigEntryAuthFailed: the token was rejected; HA asks the user for a new one
    #                          (the reauth step in config_flow.py).
    #   ConfigEntryNotReady:   Jelu is unreachable; HA retries setup later on its own.
    await coordinator.async_config_entry_first_refresh()

    # runtime_data is where an integration keeps its live objects for an entry. The platforms
    # and actions get the coordinator from here.
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JeluConfigEntry) -> bool:
    """Unload a config entry (when it's removed, disabled or reloaded).

    Removing the platforms removes the entities, which stops the coordinator's polling. The
    HTTP session is closed by HA automatically (see session.py).
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
