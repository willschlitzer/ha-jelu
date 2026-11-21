"""Shared fixtures for Jelu tests."""

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL

from custom_components.jelu.const import DOMAIN

URL = "https://jelu.example.com"
API = f"{URL}/api/v1"
TOKEN = "jelu_test_token"

SERVER_SETTINGS = {
    "appVersion": "0.88.4",
    "ldapEnabled": False,
    "metadataFetchCalibreEnabled": False,
    "metadataFetchEnabled": True,
    "metadataPlugins": [],
}


def reading_event(
    title: str = "The Left Hand of Darkness",
    event_type: str = "CURRENTLY_READING",
    end_date: str | None = None,
) -> dict[str, Any]:
    """Build a reading event shaped like Jelu's ReadingEventDto (trimmed)."""
    return {
        "id": f"event-{title}",
        "eventType": event_type,
        "startDate": "2026-11-01T00:00:00Z",
        "endDate": end_date,
        "userBook": {
            "id": f"userbook-{title}",
            "user": {"id": "user-1", "login": "reader"},
            "book": {
                "id": f"book-{title}",
                "title": title,
                "authors": [{"id": "author-1", "name": "Ursula K. Le Guin"}],
            },
        },
    }


def events_page(*events: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    """Build a Spring Data page of reading events."""
    return {
        "content": list(events),
        "totalElements": len(events) if total is None else total,
        "totalPages": 1,
        "number": 0,
        "size": 20,
        "first": True,
        "last": True,
        "empty": not events,
    }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components/ in every test."""


@pytest.fixture
def mock_jelu(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock a Jelu server that accepts the token."""
    aioclient_mock.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    aioclient_mock.get(f"{API}/reading-events/me", json=events_page(reading_event()))
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a Jelu config entry as the config flow creates it."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="jelu.example.com",
        unique_id=URL,
        data={CONF_URL: URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )


@pytest.fixture
def mock_library(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock a reader with two books in progress, 12 finished this year and 87 overall.

    The mock matches on a subset of the query string and the first match wins, so the more
    specific "finished this year" query is registered before "finished".
    """
    aioclient_mock.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    aioclient_mock.get(
        f"{API}/reading-events/me?eventTypes=CURRENTLY_READING",
        json=events_page(reading_event("Dune"), reading_event("Kindred")),
    )
    aioclient_mock.get(
        f"{API}/reading-events/me?eventTypes=FINISHED&endedAfter=2026-01-01",
        json=events_page(reading_event("Piranesi", "FINISHED"), total=12),
    )
    aioclient_mock.get(
        f"{API}/reading-events/me?eventTypes=FINISHED",
        json=events_page(reading_event("Piranesi", "FINISHED"), total=87),
    )
    return aioclient_mock
