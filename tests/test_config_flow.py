"""Tests for the Jelu config flow."""

from aiohttp import ClientError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import API, SERVER_SETTINGS, TOKEN, URL, events_page
from custom_components.jelu.const import DOMAIN

USER_INPUT = {CONF_URL: f"{URL}/", CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True}


async def test_user_flow(hass: HomeAssistant, mock_jelu: AiohttpClientMocker) -> None:
    """A good URL and token create an entry with the normalized URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "jelu.example.com"
    assert result["data"] == {
        CONF_URL: URL,
        CONF_API_TOKEN: TOKEN,
        CONF_VERIFY_SSL: True,
    }
    assert result["result"].unique_id == URL


@pytest.mark.parametrize(
    ("settings_kwargs", "events_kwargs", "errors"),
    [
        ({"exc": ClientError()}, {}, {"base": "cannot_connect"}),
        ({"text": "<html></html>"}, {}, {CONF_URL: "not_jelu"}),
        ({"json": SERVER_SETTINGS}, {"status": 401}, {CONF_API_TOKEN: "invalid_auth"}),
        ({"json": SERVER_SETTINGS}, {"status": 403}, {CONF_API_TOKEN: "missing_scope"}),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    settings_kwargs: dict,
    events_kwargs: dict,
    errors: dict[str, str],
) -> None:
    """Failures show an error on the form, and the user can then retry."""
    aioclient_mock.get(f"{API}/server-settings", **settings_kwargs)
    aioclient_mock.get(f"{API}/reading-events/me", **events_kwargs)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    aioclient_mock.get(f"{API}/reading-events/me", json=events_page())
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_url(hass: HomeAssistant) -> None:
    """A URL without a scheme is rejected before any request."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_URL: "jelu.example.com"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_jelu: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """The same server can't be added twice, even with a different spelling."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_URL: "HTTPS://Jelu.Example.com/api/v1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant, mock_jelu: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Reauth stores the new token."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "jelu_new_token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_TOKEN] == "jelu_new_token"


async def test_reauth_flow_bad_token(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A rejected token during reauth shows an error."""
    config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    aioclient_mock.get(f"{API}/reading-events/me", status=401)
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "jelu_wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_TOKEN: "invalid_auth"}
    assert config_entry.data[CONF_API_TOKEN] == TOKEN
