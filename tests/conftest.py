"""Shared test data and fixtures for the Jelu tests.

pytest loads this file automatically; every test in this folder can use what's defined here.

How these tests work
--------------------
The tests use pytest-homeassistant-custom-component, a packaged copy of Home Assistant's own
test tools. Its main fixtures (requested just by naming them as test arguments):

  hass             A real, in-memory Home Assistant instance, fresh for each test. Tests set
                   up the integration in it, then inspect states, entities and flows.
  aioclient_mock   A fake HTTP layer. Real network access is blocked in tests; instead, a
                   test registers canned responses (aioclient_mock.get(url, json=...)), and
                   every request made through HA's HTTP sessions gets the first registered
                   response whose method and URL match. Each request is also recorded in
                   aioclient_mock.mock_calls as a (method, url, body, headers) tuple, so tests
                   can check exactly what was sent.
  freezer          Controls the clock (freezegun), for tests that depend on today's date.

A typical integration test: register fake Jelu responses, add a config entry to hass, set it
up, then assert on what Home Assistant shows (hass.states.get("sensor.jelu_...")) or what
was sent to Jelu (mock_calls).

No test talks to a real Jelu server. The fake responses below mimic Jelu 0.88.4's JSON,
trimmed to the fields the integration reads.
"""

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL

from custom_components.jelu.const import DOMAIN

# The fake server every test uses.
URL = "https://jelu.example.com"
API = f"{URL}/api/v1"
TOKEN = "jelu_test_token"

# What Jelu's /server-settings returns (the one endpoint that needs no token).
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
    *,
    percent: int | None = None,
    page: int | None = None,
    page_count: int | None = None,
) -> dict[str, Any]:
    """Build one reading event as Jelu returns it (its ReadingEventDto, trimmed).

    IDs are derived from the title, e.g. "Dune" gets book ID "book-Dune" and user book ID
    "userbook-Dune", so tests can predict which URLs and IDs the integration will use.
    Every book has the same author; tests don't depend on it.
    """
    return {
        "id": f"event-{title}",
        "eventType": event_type,
        "startDate": "2026-11-01T00:00:00Z",
        "endDate": end_date,
        "userBook": {
            "id": f"userbook-{title}",
            "user": {"id": "user-1", "login": "reader"},
            "percentRead": percent,
            "currentPageNumber": page,
            "book": {
                "id": f"book-{title}",
                "title": title,
                "pageCount": page_count,
                "authors": [{"id": "author-1", "name": "Ursula K. Le Guin"}],
            },
        },
    }


def events_page(*events: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    """Wrap reading events in the paging envelope Jelu returns for lists.

    `totalElements` is the number of matches across all pages; the integration uses it as
    its count. Pass `total` to make it larger than the events listed, as in a real
    one-item "count" query.
    """
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


# Fixtures. A fixture is a function pytest runs before a test that names it as an argument,
# passing in what it returns. autouse=True runs it for every test without being named.


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components/ in every test.

    The test HA ignores custom integrations unless this built-in fixture is used.
    """


@pytest.fixture
def mock_jelu(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Fake a Jelu server that accepts the token, with one book being read.

    Every reading-events request gets the same answer, whatever its filters. That's enough
    for tests about setup and the config flow, which only need the calls to succeed.
    """
    aioclient_mock.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    aioclient_mock.get(f"{API}/reading-events/me", json=events_page(reading_event()))
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a Jelu config entry, as the config flow would have saved it.

    Tests add it to hass (config_entry.add_to_hass(hass)) and then set it up, skipping the
    config flow. It isn't set up until a test does so.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        title="jelu.example.com",
        unique_id=URL,
        data={CONF_URL: URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )


def register_library(
    aioclient_mock: AiohttpClientMocker, *, finished_total: int = 87
) -> None:
    """Register fake answers for a realistic library on aioclient_mock.

    Two books being read, 12 finished this year, `finished_total` (87) in all. Each of the
    coordinator's queries gets its own answer, so tests can check each sensor shows the
    right number. Being read: "Dune" (page 270 of 600, 45%) and "Kindred" (no progress).

    A registered URL matches a request if every query parameter in it is also in the
    request (extra ones are fine), and the first match wins. So the more specific "finished
    this year" query must be registered before plain "finished", or "finished" would answer
    both. The year is 2026 because the tests that use this freeze the clock in 2026.

    A plain function (not only the fixture below) so a test can re-register the answers,
    e.g. after making the server fail, with a different total to tell new data from old.
    """
    aioclient_mock.get(f"{API}/server-settings", json=SERVER_SETTINGS)
    aioclient_mock.get(
        f"{API}/reading-events/me?eventTypes=CURRENTLY_READING",
        json=events_page(
            reading_event("Dune", percent=45, page=270, page_count=600),
            reading_event("Kindred"),
        ),
    )
    aioclient_mock.get(
        f"{API}/reading-events/me?eventTypes=FINISHED&endedAfter=2026-01-01",
        json=events_page(reading_event("Piranesi", "FINISHED"), total=12),
    )
    aioclient_mock.get(
        f"{API}/reading-events/me?eventTypes=FINISHED",
        json=events_page(reading_event("Piranesi", "FINISHED"), total=finished_total),
    )


@pytest.fixture
def mock_library(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Fake a realistic library (see register_library) for a test."""
    register_library(aioclient_mock)
    return aioclient_mock
