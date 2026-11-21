"""HTTP session for talking to Jelu."""

from aiohttp import ClientSession, DummyCookieJar

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession


def async_create_jelu_session(
    hass: HomeAssistant, verify_ssl: bool, *, auto_cleanup: bool = True
) -> ClientSession:
    """Create a session that never stores cookies.

    Jelu (0.88.4) answers a request authenticated by API token with a SESSION cookie, and that
    cookie then authenticates on its own, ignoring the token. Home Assistant's shared session
    keeps cookies, so a revoked or mistyped token would keep "working". Without a cookie jar,
    every request is checked against the token.

    With auto_cleanup (the default) inside config entry setup, Home Assistant detaches the
    session when the entry unloads. Otherwise call session.detach() when done.
    """
    return async_create_clientsession(
        hass,
        verify_ssl=verify_ssl,
        auto_cleanup=auto_cleanup,
        cookie_jar=DummyCookieJar(),
    )
