"""Minimal async client for the Jelu REST API.

Only the endpoints the integration needs. Jelu API tokens can only reach paths on the server's
allow-list (security/TokenScope.kt). In Jelu 0.88.4 that excludes /users/me and /stats/**, so
statistics are counted from /reading-events/me instead.
"""

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from aiohttp import ClientError, ClientSession
from yarl import URL

API_PATH = "/api/v1"
REQUEST_TIMEOUT = 15


class JeluError(Exception):
    """Base error for the Jelu client."""


class JeluConnectionError(JeluError):
    """The server could not be reached or timed out."""


class JeluInvalidResponseError(JeluError):
    """The server answered, but not with what a Jelu server sends."""


class JeluAuthenticationError(JeluError):
    """The API token is missing, invalid, expired or revoked (HTTP 401)."""


class JeluPermissionError(JeluError):
    """The token is valid but may not call this endpoint (HTTP 403).

    Usually a missing scope, such as reading:read.
    """


class ReadingEventType(StrEnum):
    """Reading event types, as Jelu names them."""

    CURRENTLY_READING = "CURRENTLY_READING"
    FINISHED = "FINISHED"
    DROPPED = "DROPPED"


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """Public information about a Jelu server."""

    app_version: str


@dataclass(frozen=True, slots=True)
class ReadingEvent:
    """One reading event and the book it belongs to."""

    id: str
    event_type: ReadingEventType
    book_id: str
    title: str
    authors: list[str]
    start_date: datetime | None
    end_date: datetime | None


@dataclass(frozen=True, slots=True)
class ReadingEventPage:
    """One page of reading events, plus the total matching the query."""

    events: list[ReadingEvent]
    total: int


def normalize_url(url: str) -> str:
    """Return the server's base URL with no trailing slash or API path.

    Raises ValueError if it is not an absolute http(s) URL.
    """
    parsed = URL(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValueError(f"Not an http(s) URL: {url!r}")
    path = parsed.path.rstrip("/")
    path = path.removesuffix(API_PATH)
    return str(
        parsed.with_path(path or "/").with_query(None).with_fragment(None)
    ).rstrip("/")


class JeluClient:
    """Talks to one Jelu server with one API token."""

    def __init__(self, session: ClientSession, url: str, token: str) -> None:
        """Set up the client. `url` is the server's base URL, as given by normalize_url."""
        self._session = session
        self._api = URL(normalize_url(url) + API_PATH)
        self._token = token

    async def _get(
        self,
        path: str,
        params: Iterable[tuple[str, str]] = (),
        *,
        auth: bool = True,
    ) -> Any:
        """GET an API path and return the decoded JSON body."""
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with (
                asyncio.timeout(REQUEST_TIMEOUT),
                self._session.get(
                    self._api.with_path(self._api.path + path),
                    params=list(params),
                    headers=headers,
                ) as response,
            ):
                if response.status == HTTPStatus.UNAUTHORIZED:
                    raise JeluAuthenticationError("Jelu rejected the API token")
                if response.status == HTTPStatus.FORBIDDEN:
                    raise JeluPermissionError(f"The API token may not call {path}")
                if response.status >= HTTPStatus.BAD_REQUEST:
                    raise JeluInvalidResponseError(
                        f"Jelu returned HTTP {response.status} for {path}"
                    )
                try:
                    return await response.json()
                except (ClientError, ValueError) as err:
                    raise JeluInvalidResponseError(
                        f"Response from {path} is not JSON"
                    ) from err
        except TimeoutError as err:
            raise JeluConnectionError(f"Timed out calling {path}") from err
        except ClientError as err:
            raise JeluConnectionError(f"Error calling {path}: {err}") from err

    async def async_get_server_info(self) -> ServerInfo:
        """Return public server info. Needs no token."""
        data = await self._get("/server-settings", auth=False)
        if not isinstance(data, dict) or not isinstance(data.get("appVersion"), str):
            raise JeluInvalidResponseError("No appVersion in /server-settings")
        return ServerInfo(app_version=data["appVersion"])

    async def async_get_reading_events(
        self,
        event_types: Iterable[ReadingEventType] = (),
        *,
        ended_after: date | None = None,
        page: int = 0,
        size: int = 20,
    ) -> ReadingEventPage:
        """Return one page of the token owner's reading events, newest first.

        Needs the reading:read scope.
        """
        params = [("eventTypes", event_type.value) for event_type in event_types]
        if ended_after is not None:
            params.append(("endedAfter", ended_after.isoformat()))
        params += [("page", str(page)), ("size", str(size))]
        data = await self._get("/reading-events/me", params)
        try:
            return ReadingEventPage(
                events=[_parse_event(item) for item in data["content"]],
                total=int(data["totalElements"]),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise JeluInvalidResponseError(
                "Unexpected /reading-events/me response"
            ) from err

    async def async_count_reading_events(
        self,
        event_types: Iterable[ReadingEventType] = (),
        *,
        ended_after: date | None = None,
    ) -> int:
        """Count matching reading events, fetching a single item."""
        result = await self.async_get_reading_events(
            event_types, ended_after=ended_after, size=1
        )
        return result.total

    async def async_validate(self) -> ServerInfo:
        """Check that the URL is a Jelu server and the token can read reading events."""
        info = await self.async_get_server_info()
        await self.async_get_reading_events(size=1)
        return info


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parse_event(item: dict[str, Any]) -> ReadingEvent:
    book = item["userBook"]["book"]
    return ReadingEvent(
        id=str(item["id"]),
        event_type=ReadingEventType(item["eventType"]),
        book_id=str(book["id"]),
        title=book["title"],
        authors=[author["name"] for author in book.get("authors") or []],
        start_date=_parse_datetime(item.get("startDate")),
        end_date=_parse_datetime(item.get("endDate")),
    )
