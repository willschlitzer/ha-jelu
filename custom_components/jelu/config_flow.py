"""Config flow: the dialogs for adding, re-authenticating and reconfiguring Jelu.

HA drives a config flow as a series of "steps". Each async_step_<name>() method is one dialog:

  - It's first called with user_input=None, and returns async_show_form() to show the form.
  - When the user submits, HA calls the same method again with the entered values. It then
    returns the form again (with `errors` filled in) or finishes the flow.

The steps here:
  user         Adding the integration (Settings → Devices & services → Add integration).
  reauth       Started by HA when Jelu rejects the saved token; asks for a new one.
  reconfigure  "Reconfigure" on the integration's menu; change the URL, token or SSL setting.

The form labels, help text and error messages are in translations/en.json under "config".
Errors are returned as {field: error_key} (or "base" for the whole form), and HA shows the
matching text from that file.
"""

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

# The form fields. probatio is HA's validation library (it replaced voluptuous); a schema maps
# each field to a "selector", which decides the input widget HA draws.
TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        # Secret() hides the token's value if validation fails and reports an error.
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
    """Try the URL and token against the real server.

    Returns (server info, {}) if they work, or (None, form errors) if not. Each error key is
    one of the "error" messages in translations/en.json.
    """
    # A short-lived session just for this check, closed in `finally` below. (Sessions made
    # during entry setup are closed by HA; this one isn't, so it's closed by hand.)
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
        # A bug, not a user mistake: log the traceback, show a generic error.
        _LOGGER.exception("Unexpected error validating Jelu credentials")
        return None, {"base": "unknown"}
    finally:
        session.detach()


def _entry_title(url: str) -> str:
    """Name the entry after the server, without the scheme, e.g. jelu.example.com."""
    return url.split("://", 1)[1]


class JeluConfigFlow(ConfigFlow, domain=DOMAIN):
    """The Jelu config flow. `domain=DOMAIN` is how HA knows which integration it's for."""

    # Version of the saved entry data. Bump it (and add a migration) if its format changes.
    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a Jelu server: ask for the URL and an API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                # Tidy the URL ("https://host/api/v1/" → "https://host"), or reject it.
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                user_input = {**user_input, CONF_URL: url}
                # Each config entry needs an ID that's the same however it's added, so HA can
                # refuse duplicates. The natural choice would be the Jelu user's ID, but tokens
                # can't read /users/me, so the server URL is used instead.
                await self.async_set_unique_id(url.lower())
                self._abort_if_unique_id_configured()
                info, errors = await _async_validate(self.hass, user_input)
                if info is not None:
                    # Saves the config entry; HA then runs async_setup_entry in __init__.py.
                    return self.async_create_entry(
                        title=_entry_title(url), data=user_input
                    )

        # First visit, or a failed submit: show the form, keeping what the user had entered.
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            # Fills {example_url} in the URL help text. It's passed in here because hassfest
            # (HA's validator) doesn't allow URLs inside translation strings.
            description_placeholders={"example_url": "https://jelu.example.com"},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication. HA calls this when Jelu rejects the saved token.

        It shows no form itself: HA requires the reauth entry point to have this name and
        signature, and the dialog is the next step.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API token, keeping the URL and SSL setting."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
            info, errors = await _async_validate(self.hass, data)
            if info is not None:
                # Saves the new token and reloads the entry, which reconnects with it.
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={CONF_URL: entry.data[CONF_URL]},  # fills {url}
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the URL, token or SSL setting, e.g. to use a token that can write."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                user_input = {**user_input, CONF_URL: url}
                # The URL is the unique ID, so moving this entry to a URL that another entry
                # already uses would create a duplicate. Refuse that.
                if any(
                    other.unique_id == url.lower()
                    for other in self._async_current_entries(include_ignore=False)
                    if other.entry_id != entry.entry_id
                ):
                    return self.async_abort(reason="already_configured")
                info, errors = await _async_validate(self.hass, user_input)
                if info is not None:
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=url.lower(),
                        title=_entry_title(url),
                        data=user_input,
                    )

        # Pre-fill everything but the token, so the saved token is never shown in the form;
        # the user enters it (or a new one) again.
        suggested = {
            CONF_URL: entry.data[CONF_URL],
            CONF_VERIFY_SSL: entry.data[CONF_VERIFY_SSL],
            **{k: v for k, v in (user_input or {}).items() if k != CONF_API_TOKEN},
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, suggested
            ),
            description_placeholders={"example_url": "https://jelu.example.com"},
            errors=errors,
        )
