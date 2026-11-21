"""Config flow for the Jelu integration."""

from collections.abc import Mapping
import logging
from typing import Any, override

import probatio

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    JeluAuthenticationError,
    JeluClient,
    JeluConnectionError,
    JeluInvalidResponseError,
    JeluPermissionError,
    ServerInfo,
    normalize_url,
)
from .const import DOMAIN
from .session import async_create_jelu_session

_LOGGER = logging.getLogger(__name__)

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        probatio.Required(probatio.Secret(CONF_API_TOKEN)): TOKEN_SELECTOR,
        probatio.Optional(CONF_VERIFY_SSL, default=True): BooleanSelector(),
    }
)

STEP_REAUTH_DATA_SCHEMA = probatio.Schema(
    {probatio.Required(probatio.Secret(CONF_API_TOKEN)): TOKEN_SELECTOR}
)


async def _async_validate(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> tuple[ServerInfo | None, dict[str, str]]:
    """Try the URL and token. Return the server info, or form errors."""
    session = async_create_jelu_session(hass, data[CONF_VERIFY_SSL], auto_cleanup=False)
    client = JeluClient(session, data[CONF_URL], data[CONF_API_TOKEN])
    try:
        return await client.async_validate(), {}
    except JeluConnectionError:
        return None, {"base": "cannot_connect"}
    except JeluInvalidResponseError:
        return None, {CONF_URL: "not_jelu"}
    except JeluAuthenticationError:
        return None, {CONF_API_TOKEN: "invalid_auth"}
    except JeluPermissionError:
        return None, {CONF_API_TOKEN: "missing_scope"}
    except Exception:
        _LOGGER.exception("Unexpected error validating Jelu credentials")
        return None, {"base": "unknown"}
    finally:
        session.detach()


def _entry_title(url: str) -> str:
    """Entry title: the URL without its scheme, e.g. jelu.example.com."""
    return url.split("://", 1)[1]


class JeluConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Jelu."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the server URL and an API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                user_input = {**user_input, CONF_URL: url}
                # Jelu tokens can't read /users/me, so the server URL is the unique ID.
                await self.async_set_unique_id(url.lower())
                self._abort_if_unique_id_configured()
                info, errors = await _async_validate(self.hass, user_input)
                if info is not None:
                    return self.async_create_entry(
                        title=_entry_title(url), data=user_input
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after Jelu rejected the token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API token."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
            info, errors = await _async_validate(self.hass, data)
            if info is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={CONF_URL: entry.data[CONF_URL]},
            errors=errors,
        )
