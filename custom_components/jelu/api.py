"""Minimal async client for the Jelu REST API.

This module knows nothing about Home Assistant: it takes an aiohttp session, a URL and a token,
and returns plain Python objects or raises the Jelu* exceptions below. Keeping it separate
means it could later become its own package (e.g. for inclusion in HA core).

Jelu's data model, as far as this client uses it:

  book        A book in the library: title, authors, page count. Shared by all users.
  user book   One user's copy of a book: their progress (current page, percent read),
              notes, owned/borrowed and so on. Progress is updated here.
  reading     One read-through of a user book, with a type (CURRENTLY_READING, FINISHED,
  event       DROPPED) and start/end dates. Starting a book opens a CURRENTLY_READING event;
              finishing or dropping it changes that event's type and sets its end date.
              Rereading starts a new event, which is why a reread counts as another finish.

So "the books I'm reading" means "my CURRENTLY_READING reading events", and the counts are
counts of reading events.

Access: Jelu API tokens can only reach paths on the server's allow-list (TokenScope.kt in
Jelu). In Jelu 0.88.4 that excludes /users/me and /stats/**, so statistics are counted from
/reading-events/me instead. Reading needs the reading:read scope; changing progress or a
book's status needs reading:write.
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


# Errors. The callers (config flow, coordinator) catch these and decide what the user sees,
# so each kind of failure gets its own class.


class JeluError(Exception):
    """Base error for the Jelu client. Catch this to handle any of the ones below."""


class JeluConnectionError(JeluError):
    """The server could not be reached or timed out."""


class JeluInvalidResponseError(JeluError):
    """The server answered, but not with what a Jelu server sends."""


class JeluAuthenticationError(JeluError):
    """The API token is missing, invalid, expired or revoked (HTTP 401)."""


class JeluPermissionError(JeluError):
    """The token is valid but may not call this endpoint (HTTP 403).

    Usually a missing scope, such as reading:read or reading:write.
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
    """One reading event, flattened together with its user book and book.

    Jelu returns these nested (event → userBook → book); _parse_event() at the bottom of this
    file picks out the fields used here.
    """

    id: str  # the reading event's ID
    event_type: ReadingEventType
    book_id: str  # the book's ID: used to finish or drop it
    user_book_id: str  # the user book's ID: used to set progress
    title: str
    authors: list[str]
    start_date: datetime | None
    end_date: datetime | None  # None while the book is still being read
    # Progress, from the user book. Any of these can be missing, e.g. a book with no known
    # page count only has a percentage.
    percent_read: int | None
    current_page: int | None
    page_count: int | None


@dataclass(frozen=True, slots=True)
class ReadingEventPage:
    """One page of reading events, plus the total matching the query."""

    events: list[ReadingEvent]
    total: int


# Helpers and the client itself.


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
        self._session = (
            session  # created by session.py; the client doesn't own or close it
        )
        self._api = URL(
            normalize_url(url) + API_PATH
        )  # e.g. https://jelu.example.com/api/v1
        self._token = token

    async def _request(
        self,
        method: str,
        path: str,
        params: Iterable[tuple[str, str]] = (),
        *,
        json: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        """Call an API path and return the decoded JSON body.

        Every request goes through here, so this is the one place that turns HTTP status
        codes and network errors into the exceptions above. `path` is relative to /api/v1;
        `params` become the query string, `json` the request body. `auth=False` leaves out
        the token, for the one endpoint that doesn't need it.
        """
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            # Give up after REQUEST_TIMEOUT seconds, rather than waiting on a hung server.
            async with (
                asyncio.timeout(REQUEST_TIMEOUT),
                self._session.request(
                    method,
                    self._api.with_path(self._api.path + path),
                    params=list(params),
                    json=json,
                    headers=headers,
                ) as response,
            ):
                # 401: no valid token. 403: valid token, but not allowed here (missing scope).
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
        # The status checks above raise Jelu* errors, which pass straight through these.
        except TimeoutError as err:
            raise JeluConnectionError(f"Timed out calling {path}") from err
        except ClientError as err:
            raise JeluConnectionError(f"Error calling {path}: {err}") from err

    async def async_get_server_info(self) -> ServerInfo:
        """Return public server info. Needs no token."""
        data = await self._request("GET", "/server-settings", auth=False)
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
        # A list of pairs rather than a dict, because eventTypes may repeat:
        # ?eventTypes=FINISHED&eventTypes=DROPPED
        params = [("eventTypes", event_type.value) for event_type in event_types]
        if ended_after is not None:
            params.append(("endedAfter", ended_after.isoformat()))
        params += [("page", str(page)), ("size", str(size))]
        data = await self._request("GET", "/reading-events/me", params)
        # Jelu returns a "page": {"content": [the events], "totalElements": total matching,
        # ...}. Any missing or malformed field means this isn't the reply we expect.
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
        """Count matching reading events.

        Jelu reports the total number of matches with every page, so asking for a one-item
        page is a cheap way to count.
        """
        result = await self.async_get_reading_events(
            event_types, ended_after=ended_after, size=1
        )
        return result.total

    async def async_set_progress(
        self,
        user_book_id: str,
        *,
        page: int | None = None,
        percent: int | None = None,
    ) -> None:
        """Set reading progress for one of the user's books. Needs reading:write.

        Give exactly one of `page` or `percent`. If the book has a page count, Jelu works out the
        other value; if not, the other value is cleared. Reaching 100% or the last page makes
        Jelu mark the book finished.

        PUT /userbooks/{id} always overwrites both progress fields (other fields are only changed
        when given), so the one not being set is sent as null on purpose.
        """
        if (page is None) == (percent is None):
            raise ValueError("Give exactly one of page or percent")
        await self._request(
            "PUT",
            f"/userbooks/{user_book_id}",
            json={"currentPageNumber": page, "percentRead": percent},
        )

    async def async_set_reading_status(
        self, book_id: str, event_type: ReadingEventType
    ) -> None:
        """Mark a book finished or dropped (or started) as of now. Needs reading:write.

        This is what Jelu's own UI does: the book's open CURRENTLY_READING event is converted to
        the new type and ended now, rather than a second event being created. FINISHED also sets
        progress to 100%; DROPPED keeps the current progress.
        """
        await self._request(
            "POST",
            "/reading-events",
            json={"eventType": event_type.value, "bookId": book_id},
        )

    async def async_validate(self) -> ServerInfo:
        """Check that the URL is a Jelu server and the token can read reading events.

        Used by the config flow before saving anything. The first call needs no token, so a
        failure there means a wrong URL; a failure on the second means a token problem.
        """
        info = await self.async_get_server_info()
        await self.async_get_reading_events(size=1)
        return info


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse Jelu's ISO 8601 timestamps, e.g. "2026-06-17T00:00:00-04:00"."""
    return datetime.fromisoformat(value) if value else None


def _parse_event(item: dict[str, Any]) -> ReadingEvent:
    """Turn one reading event from Jelu's JSON into a ReadingEvent.

    Required fields use item["..."], so a missing one raises KeyError (reported by the
    caller as an invalid response). Optional ones use .get(), which gives None.
    """
    user_book = item["userBook"]
    book = user_book["book"]
    return ReadingEvent(
        id=str(item["id"]),
        event_type=ReadingEventType(item["eventType"]),
        book_id=str(book["id"]),
        user_book_id=str(user_book["id"]),
        title=book["title"],
        authors=[author["name"] for author in book.get("authors") or []],
        start_date=_parse_datetime(item.get("startDate")),
        end_date=_parse_datetime(item.get("endDate")),
        percent_read=user_book.get("percentRead"),
        current_page=user_book.get("currentPageNumber"),
        page_count=book.get("pageCount"),
    )
