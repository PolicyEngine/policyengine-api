"""A client for one GitHub repository's issues and labels, with rate limiting."""

from __future__ import annotations

import json
import time
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from telemetry_error_issues.transport import (
    ApiError,
    HttpRequest,
    HttpResponse,
    urllib_transport,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_PAGE_SIZE = 100

# GitHub asks clients to send content-creating requests one at a time, at
# least a second apart, and to wait as its rate-limit responses say.
MIN_SECONDS_BETWEEN_WRITES = 1.0
MAX_RATE_LIMIT_RETRIES = 3
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60
MAX_RATE_LIMIT_WAIT_SECONDS = 300
RATE_LIMIT_STATUSES = frozenset({HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS})


class GitHubError(ApiError):
    """A GitHub request failed."""

    service = "GitHub"


class GitHubLabelError(GitHubError):
    """GitHub didn't apply the labels the job asked for."""


def _seconds_until_reset(response: HttpResponse) -> int | None:
    """Return the seconds from the response's ``date`` to ``x-ratelimit-reset``."""
    reset = response.headers.get("x-ratelimit-reset", "")
    sent = response.headers.get("date")
    if not (reset.isascii() and reset.isdigit()) or not sent:
        return None
    try:
        sent_at = parsedate_to_datetime(sent)
    except (TypeError, ValueError):
        return None
    return max(int(reset) - int(sent_at.timestamp()), 0)


def _rate_limit_wait(response: HttpResponse) -> int | None:
    """Return the seconds to wait before retrying a rate-limited request.

    Follows GitHub's guidance: wait for ``retry-after``; when no requests
    remain, wait until ``x-ratelimit-reset``; otherwise wait a minute. A 403
    whose headers and message don't mention a rate limit is a permission
    failure, so it isn't retried. The message is only searched, never printed.
    """
    if response.status not in RATE_LIMIT_STATUSES:
        return None
    retry_after = response.headers.get("retry-after", "")
    if retry_after.isascii() and retry_after.isdigit():
        seconds = int(retry_after)
    elif response.headers.get("x-ratelimit-remaining") == "0":
        until_reset = _seconds_until_reset(response)
        seconds = (
            DEFAULT_RATE_LIMIT_WAIT_SECONDS if until_reset is None else until_reset
        )
    elif (
        response.status == HTTPStatus.TOO_MANY_REQUESTS
        or b"rate limit" in response.body.lower()
    ):
        seconds = DEFAULT_RATE_LIMIT_WAIT_SECONDS
    else:
        return None
    return seconds if seconds <= MAX_RATE_LIMIT_WAIT_SECONDS else None


def _json_object(response: HttpResponse) -> dict[str, Any]:
    payload = json.loads(response.body)
    if not isinstance(payload, dict):
        msg = "GitHub returned an unexpected response"
        raise GitHubError(msg)
    return payload


def _json_list(response: HttpResponse) -> list[dict[str, Any]]:
    payload = json.loads(response.body)
    if not isinstance(payload, list):
        msg = "GitHub returned an unexpected response"
        raise GitHubError(msg)
    return payload


class GitHubClient:
    """Reads and writes one repository's issues and labels.

    Writes go one at a time, at least a second apart. A rate-limited request is
    retried after the wait GitHub asks for, up to three times.
    """

    def __init__(
        self,
        repository: str,
        credential: str,
        transport: Callable[[HttpRequest], HttpResponse] = urllib_transport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Send requests for ``repository`` (``owner/name``) with ``credential``."""
        self._repository_url = f"{GITHUB_API}/repos/{repository}"
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {credential}",
            "User-Agent": "policyengine-telemetry-error-issues",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._last_write: float | None = None

    def list_issues(self, creator: str) -> list[dict[str, Any]]:
        """Return the open and closed issues ``creator`` opened, without PRs."""
        issues = self._pages("/issues", {"state": "all", "creator": creator})
        return [issue for issue in issues if "pull_request" not in issue]

    def list_labels(self) -> set[str]:
        """Return the names of the repository's labels."""
        return {label["name"] for label in self._pages("/labels", {})}

    def create_label(self, name: str, color: str, description: str) -> None:
        """Create a label."""
        self._send(
            "POST",
            "/labels",
            {"name": name, "color": color, "description": description},
        )

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        """Open an issue and return it as GitHub describes it."""
        payload = {"title": title, "body": body, "labels": labels}
        return _json_object(self._send("POST", "/issues", payload))

    def update_issue(self, number: int, fields: Mapping[str, object]) -> None:
        """Change an issue's fields, such as its body or state."""
        self._send("PATCH", f"/issues/{number}", fields)

    def add_labels(self, number: int, labels: list[str]) -> set[str]:
        """Add labels to an issue and return all the labels it now has."""
        response = self._send("POST", f"/issues/{number}/labels", {"labels": labels})
        return {label["name"] for label in _json_list(response)}

    def add_comment(self, number: int, body: str) -> None:
        """Comment on an issue."""
        self._send("POST", f"/issues/{number}/comments", {"body": body})

    def _pages(self, path: str, parameters: Mapping[str, str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urlencode(
                {**parameters, "per_page": GITHUB_PAGE_SIZE, "page": page}
            )
            batch = _json_list(self._send("GET", f"{path}?{query}", None))
            items.extend(batch)
            if len(batch) < GITHUB_PAGE_SIZE:
                return items
            page += 1

    def _wait_between_writes(self) -> None:
        if self._last_write is None:
            return
        elapsed = self._clock() - self._last_write
        if elapsed < MIN_SECONDS_BETWEEN_WRITES:
            self._sleep(MIN_SECONDS_BETWEEN_WRITES - elapsed)

    def _send(
        self, method: str, path: str, body: Mapping[str, object] | None
    ) -> HttpResponse:
        headers = dict(self._headers)
        encoded = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(body).encode()
        request = HttpRequest(method, f"{self._repository_url}{path}", headers, encoded)
        is_write = method != "GET"
        for retry in range(MAX_RATE_LIMIT_RETRIES + 1):
            if is_write:
                self._wait_between_writes()
            response = self._transport(request)
            if is_write:
                self._last_write = self._clock()
            wait = _rate_limit_wait(response)
            if wait is None or retry == MAX_RATE_LIMIT_RETRIES:
                break
            self._sleep(wait)
        if response.status >= HTTPStatus.BAD_REQUEST:
            raise GitHubError.from_response(response)
        return response
