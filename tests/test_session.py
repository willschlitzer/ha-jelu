"""Tests for the Jelu HTTP session."""

from aiohttp import DummyCookieJar

from homeassistant.core import HomeAssistant

from custom_components.jelu.session import async_create_jelu_session


async def test_session_stores_no_cookies(hass: HomeAssistant) -> None:
    """Jelu's SESSION cookie must never be kept, or a revoked token keeps working."""
    session = async_create_jelu_session(hass, verify_ssl=True, auto_cleanup=False)
    try:
        assert isinstance(session.cookie_jar, DummyCookieJar)
    finally:
        session.detach()
