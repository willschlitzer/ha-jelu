"""Tests for the Jelu HTTP session (session.py).

Jelu answers a token-authenticated request with a session cookie that then works on its
own, without the token (see session.py). This guards against the integration ever
switching to a session that stores cookies.
"""

from aiohttp import DummyCookieJar

from homeassistant.core import HomeAssistant

from custom_components.jelu.session import async_create_jelu_session


async def test_session_stores_no_cookies(hass: HomeAssistant) -> None:
    """Jelu's SESSION cookie must never be kept, or a revoked token keeps working."""
    # auto_cleanup=False because this isn't inside an entry setup; detach() closes it below.
    session = async_create_jelu_session(hass, verify_ssl=True, auto_cleanup=False)
    try:
        assert isinstance(session.cookie_jar, DummyCookieJar)
    finally:
        session.detach()
