"""Tests for the Jelu API client."""

from datetime import UTC, date, datetime

from aiohttp import ClientError
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import API, TOKEN, URL, events_page, reading_event
from custom_components.jelu.api import (
    JeluAuthenticationError,
    JeluClient,
    JeluConnectionError,
    JeluInvalidResponseError,
    JeluPermissionError,
    ReadingEventType,
    normalize_url,
)


@pytest.fixture
def client(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> JeluClient:
    """Return a client that uses Home Assistant's (mocked) session."""
    return JeluClient(async_get_clientsession(hass), URL, TOKEN)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://jelu.example.com", "https://jelu.example.com"),
        ("  https://jelu.example.com/  ", "https://jelu.example.com"),
        ("https://jelu.example.com/api/v1/", "https://jelu.example.com"),
        ("http://192.168.1.5:11111", "http://192.168.1.5:11111"),
        ("https://example.com/jelu/", "https://example.com/jelu"),
        ("https://jelu.example.com/?x=1#top", "https://jelu.example.com"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    """URLs are reduced to the server's base URL."""
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["jelu.example.com", "ftp://jelu.example.com", ""])
def test_normalize_url_rejects(raw: str) -> None:
    """Anything that is not an absolute http(s) URL is rejected."""
    with pytest.raises(ValueError):
        normalize_url(raw)


async def test_server_info_needs_no_token(
    client: JeluClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """/server-settings is called without the token."""
    aioclient_mock.get(f"{API}/server-settings", json={"appVersion": "0.88.4"})
    info = await client.async_get_server_info()
    assert info.app_version == "0.88.4"
    _, _, _, headers = aioclient_mock.mock_calls[0]
    assert "Authorization" not in headers


@pytest.mark.parametrize(
    "kwargs",
    [{"text": "<html>not jelu</html>"}, {"json": {"hello": "world"}}],
)
async def test_server_info_not_jelu(
    client: JeluClient, aioclient_mock: AiohttpClientMocker, kwargs: dict
) -> None:
    """A server that doesn't answer like Jelu is reported as such."""
    aioclient_mock.get(f"{API}/server-settings", **kwargs)
    with pytest.raises(JeluInvalidResponseError):
        await client.async_get_server_info()


async def test_reading_events(
    client: JeluClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Events are parsed and the filters are sent as query parameters."""
    aioclient_mock.get(
        f"{API}/reading-events/me",
        json=events_page(
            reading_event("Dune", "FINISHED", "2026-03-04T00:00:00Z"), total=42
        ),
    )
    page = await client.async_get_reading_events(
        [ReadingEventType.FINISHED, ReadingEventType.DROPPED],
        ended_after=date(2026, 1, 1),
        size=5,
    )

    assert page.total == 42
    [event] = page.events
    assert event.title == "Dune"
    assert event.authors == ["Ursula K. Le Guin"]
    assert event.event_type is ReadingEventType.FINISHED
    assert event.end_date == datetime(2026, 3, 4, tzinfo=UTC)

    _, url, _, headers = aioclient_mock.mock_calls[0]
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert url.query.getall("eventTypes") == ["FINISHED", "DROPPED"]
    assert url.query["endedAfter"] == "2026-01-01"
    assert url.query["size"] == "5"


async def test_count_reading_events(
    client: JeluClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Counting fetches one item and returns the total."""
    aioclient_mock.get(
        f"{API}/reading-events/me", json=events_page(reading_event(), total=7)
    )
    assert await client.async_count_reading_events([ReadingEventType.FINISHED]) == 7
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query["size"] == "1"


async def test_reading_events_bad_shape(
    client: JeluClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A page without the expected fields is an invalid response."""
    aioclient_mock.get(f"{API}/reading-events/me", json={"content": [{}]})
    with pytest.raises(JeluInvalidResponseError):
        await client.async_get_reading_events()


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"status": 401}, JeluAuthenticationError),
        ({"status": 403}, JeluPermissionError),
        ({"status": 500}, JeluInvalidResponseError),
        ({"exc": ClientError()}, JeluConnectionError),
        ({"exc": TimeoutError()}, JeluConnectionError),
    ],
)
async def test_errors(
    client: JeluClient,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict,
    error: type[Exception],
) -> None:
    """HTTP and network failures map to the client's errors."""
    aioclient_mock.get(f"{API}/reading-events/me", **mock_kwargs)
    with pytest.raises(error):
        await client.async_get_reading_events()
