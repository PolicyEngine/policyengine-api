"""Optional Auth0 Management API access for account deletion and user profiles.

Two settings groups each configure one Management API machine-to-machine
client, and both use the same client code, token cache and secret handling:

- ``AUTH0_MANAGEMENT_*``: ``DELETE /v2/me`` removes the Auth0 user only when a
  client with the ``delete:users`` permission is configured. Without it,
  account deletion removes only Public API data and logs that the Auth0
  deletion was skipped. Deployments allow it in production only.
- ``AUTH0_USER_PROFILES_*``: the admin user routes read users' emails and
  names from Auth0, invitations are accepted against the invitee's verified
  email, and type-change emails find the user's address, only when a client
  with the ``read:users`` permission is configured; nothing they read is
  stored. Deployments allow it in staging and production.

Each group is all-or-none: a domain, a client ID, and exactly one
client-secret source (a direct value or a Secret Manager resource, matching
the gateway-auth pattern). The domain must be the tenant's canonical Auth0
domain (for example ``policyengine.us.auth0.com``): the Management API
audience is not served on custom domains. This module never logs, or puts in
an error message, an email, a subject, a token or a secret.
"""

from __future__ import annotations

import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

import httpx

from policyengine_api.libs.auth0_management_settings import (
    AUTH0_MANAGEMENT_CLIENT_ID_ENV,
    AUTH0_MANAGEMENT_CLIENT_SECRET_ENV,
    AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV,
    AUTH0_MANAGEMENT_DOMAIN_ENV,
    AUTH0_MANAGEMENT_ENV_VARS,
    AUTH0_MANAGEMENT_SETTING_NAMES,
    AUTH0_USER_PROFILE_SETTING_NAMES,
    DOMAIN_PATTERN,
    SECRET_RESOURCE_PATTERN,
    Auth0ClientSettingNames,
    Auth0ManagementConfigurationError,
    Auth0ManagementSettings,
    load_auth0_management_settings,
    load_auth0_user_profile_settings,
)
from policyengine_api.libs.rate_limit_wait_budget import RateLimitWaitBudget

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping

# The settings moved to auth0_management_settings; they are still imported
# from here.
__all__ = [
    "AUTH0_MANAGEMENT_CLIENT_ID_ENV",
    "AUTH0_MANAGEMENT_CLIENT_SECRET_ENV",
    "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV",
    "AUTH0_MANAGEMENT_DOMAIN_ENV",
    "AUTH0_MANAGEMENT_ENV_VARS",
    "AUTH0_MANAGEMENT_SETTING_NAMES",
    "AUTH0_USER_PROFILE_SETTING_NAMES",
    "DOMAIN_PATTERN",
    "SECRET_RESOURCE_PATTERN",
    "Auth0ClientSettingNames",
    "Auth0ManagementClient",
    "Auth0ManagementConfigurationError",
    "Auth0ManagementError",
    "Auth0ManagementSettings",
    "Auth0UserIdSearch",
    "Auth0UserProfile",
    "Auth0UserProfilesUnavailableError",
    "UserProfileReader",
    "build_auth0_user_deleter",
    "build_auth0_user_profile_reader",
    "email_search_query",
    "load_auth0_management_settings",
    "load_auth0_user_profile_settings",
]

HTTP_TIMEOUT_SECONDS = 10.0
TOKEN_REFRESH_MARGIN_SECONDS = 60
# Every search page is sorted by user ID, so pages don't shift between requests.
USER_SEARCH_SORT = "user_id:1"

# Auth0's user search (search engine v3) answers at most 50 users a page on
# its public cloud, and at most 1,000 results for one query; an email search's
# match limit stays below that.
USER_SEARCH_PAGE_SIZE = 50
USER_SEARCH_RESULT_LIMIT = 1000
USER_PROFILE_FIELDS = "user_id,email,email_verified,given_name,family_name,name"
# A query term may start with a wildcard only when at least this many
# characters follow it.
LEADING_WILDCARD_MINIMUM_CHARACTERS = 3
# Characters with a meaning in Auth0's Lucene query syntax; whitespace too.
LUCENE_SPECIAL_CHARACTERS = frozenset('+-&|!(){}[]^"~*?:\\/')
MAXIMUM_EMAIL_LENGTH = 320
MAXIMUM_NAME_LENGTH = 255


class Auth0ManagementError(RuntimeError):
    """Raised when the Management API rejects or fails a request.

    ``cause`` says why, with no personal data: ``http_<status>`` for a
    request's answer, ``token_http_<status>`` or ``token_unreadable_answer``
    for the token request, ``timeout``, ``connection_error``,
    ``unreadable_answer`` or ``secret_unavailable``.
    """

    def __init__(self, message: str, *, cause: str = "management_api_error") -> None:
        """Keep ``cause`` with the message; neither names a person."""
        super().__init__(message)
        self.cause = cause


class Auth0UserProfilesUnavailableError(Auth0ManagementError):
    """Raised when users' profiles can't be read: any failure of a profile read.

    Timeouts, connection errors, a refused or failed token request, a missing
    ``read:users`` permission (``http_403``), rate limiting (``http_429``,
    after at most one short wait), server errors (``http_500`` and so on)
    and an answer that isn't a list of users, or for a read by ID isn't that
    user, all raise it, each with its ``cause``. The message names at most
    that cause.
    """


def _transport_cause(error: httpx.HTTPError) -> str:
    """Name a failed request's cause: a timeout, or no usable connection."""
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    return "connection_error"


def _seconds(value: str | None) -> float | None:
    """Read a header's number of seconds, or None when it isn't one."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) else None


@dataclass(frozen=True)
class Auth0UserProfile:
    """What the Public API reads about one Auth0 user; never stored.

    Each text is stripped, and absent when Auth0 sent none, sent an empty one
    or sent something other than text. ``email_verified`` is true only when
    Auth0 says so.
    """

    user_id: str
    email: str | None
    email_verified: bool
    given_name: str | None
    family_name: str | None
    name: str | None


@dataclass(frozen=True)
class Auth0UserIdSearch:
    """The Auth0 user IDs an email search found, each once, in Auth0's order.

    ``more_than_limit`` is true when more users matched than the search's
    match limit; ``user_ids`` is then empty.
    """

    user_ids: tuple[str, ...]
    more_than_limit: bool


class UserProfileReader(Protocol):
    """The read-only part of the client: profile reads and email searches.

    Each method raises Auth0UserProfilesUnavailableError, with its cause,
    when Auth0 can't answer. Nothing it returns is stored.
    """

    def read_user_profiles(
        self,
        user_ids: Iterable[str],
        *,
        wait_budget: RateLimitWaitBudget | None = None,
    ) -> Mapping[str, Auth0UserProfile]:
        """Return the profiles Auth0 has for these user IDs, by user ID.

        Rate-limit waits are spent from ``wait_budget``, else from a budget
        of this call's own.
        """
        ...

    def search_user_ids_by_email(
        self,
        text: str,
        *,
        match_limit: int,
        wait_budget: RateLimitWaitBudget | None = None,
    ) -> Auth0UserIdSearch:
        """Return the IDs of users whose email contains ``text``.

        The result says when more than ``match_limit`` users match instead.
        Rate-limit waits are spent from ``wait_budget``, else from a budget
        of this call's own.
        """
        ...

    def read_user_profile(
        self, user_id: str, *, wait_budget: RateLimitWaitBudget | None = None
    ) -> Auth0UserProfile | None:
        """Return one user's profile as Auth0 has it now, or None if unknown.

        Unlike the search the other reads use, it sees a user created or
        changed moments ago. Rate-limit waits are spent from ``wait_budget``,
        else from a budget of this call's own.
        """
        ...


def _quoted_user_id(user_id: str) -> str:
    """Quote a user ID as a Lucene phrase; its quotes and backslashes are escaped."""
    escaped = user_id.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _escaped_search_text(text: str) -> str:
    """Escape every character with a meaning in Lucene, and whitespace."""
    return "".join(
        f"\\{character}"
        if character in LUCENE_SPECIAL_CHARACTERS or character.isspace()
        else character
        for character in text
    )


def email_search_query(text: str) -> str:
    """Return the Auth0 query for users whose email contains ``text``.

    Matching ignores case. With fewer than three characters, a leading
    wildcard isn't allowed, so only emails that start with ``text`` match.
    Raise ValueError for text with ``<`` or ``>``: Auth0's query syntax
    reads them as a range, and can't escape them.
    """
    if "<" in text or ">" in text:
        msg = "email search text can't contain < or >"
        raise ValueError(msg)
    lowered = text.lower()
    escaped = _escaped_search_text(lowered)
    if len(lowered) >= LEADING_WILDCARD_MINIMUM_CHARACTERS:
        return f"email:*{escaped}*"
    return f"email:{escaped}*"


def _profile_text(value: object, maximum_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > maximum_length:
        return None
    return text


def _user_profile(payload: object) -> Auth0UserProfile | None:
    """Read one user of an answer, or ``None`` when it has no user ID."""
    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        return None
    return Auth0UserProfile(
        user_id=user_id,
        email=_profile_text(payload.get("email"), MAXIMUM_EMAIL_LENGTH),
        email_verified=payload.get("email_verified") is True,
        given_name=_profile_text(payload.get("given_name"), MAXIMUM_NAME_LENGTH),
        family_name=_profile_text(payload.get("family_name"), MAXIMUM_NAME_LENGTH),
        name=_profile_text(payload.get("name"), MAXIMUM_NAME_LENGTH),
    )


@cache
def _load_secret_from_secret_manager(resource_name: str) -> str:
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource_name})
    return response.payload.data.decode("utf-8")


class Auth0ManagementClient:
    """Delete or read Auth0 users through a cached client-credentials token."""

    def __init__(
        self,
        settings: Auth0ManagementSettings,
        *,
        http_client: httpx.Client | None = None,
        secret_loader: Callable[[str], str] = _load_secret_from_secret_manager,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Use ``settings`` for the tenant and client credentials.

        ``http_client`` replaces the per-request and per-operation clients
        (tests pass a mock transport), and ``secret_loader`` reads
        ``client_secret_resource`` when no direct secret is set. ``sleep``
        waits before a rate-limited read's retry, and ``clock`` gives the
        current Unix time for Auth0's rate-limit reset.
        """
        self._settings = settings
        self._http_client = http_client
        self._secret_loader = secret_loader
        self._sleep = sleep
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    @property
    def _base_url(self) -> str:
        return f"https://{self._settings.domain}"

    def _client_secret(self) -> str:
        if self._settings.client_secret:
            return self._settings.client_secret
        try:
            secret = self._secret_loader(self._settings.client_secret_resource).strip()
        except Exception as error:
            msg = "the Management API client secret could not be loaded"
            raise Auth0ManagementError(msg, cause="secret_unavailable") from error
        if not secret:
            msg = "the Management API client secret is empty"
            raise Auth0ManagementError(msg, cause="secret_unavailable")
        return secret

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        try:
            if self._http_client is not None:
                return self._http_client.request(method, url, **kwargs)  # type: ignore[arg-type]
            with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
                return client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as error:
            msg = f"Management API request failed: {type(error).__name__}"
            raise Auth0ManagementError(msg, cause=_transport_cause(error)) from error

    def _send(
        self, http_client: httpx.Client, request: httpx.Request
    ) -> httpx.Response:
        """Send one request through an operation's own HTTP client."""
        try:
            return http_client.send(request)
        except httpx.HTTPError as error:
            msg = f"Management API request failed: {type(error).__name__}"
            raise Auth0ManagementError(msg, cause=_transport_cause(error)) from error

    @contextmanager
    def _operation_http_client(self) -> Iterator[httpx.Client]:
        """Yield one HTTP client, so one connection serves an operation's requests."""
        if self._http_client is not None:
            yield self._http_client
            return
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as http_client:
            yield http_client

    def _access_token(self, http_client: httpx.Client | None = None) -> str:
        """Return the cached token, or request one, through ``http_client`` if given."""
        with self._lock:
            now = time.time()
            if (
                self._token is not None
                and now < self._expires_at - TOKEN_REFRESH_MARGIN_SECONDS
            ):
                return self._token
            token_url = f"{self._base_url}/oauth/token"
            token_request = {
                "grant_type": "client_credentials",
                "client_id": self._settings.client_id,
                "client_secret": self._client_secret(),
                "audience": f"{self._base_url}/api/v2/",
            }
            response = (
                self._request("POST", token_url, json=token_request)
                if http_client is None
                else self._send(
                    http_client,
                    http_client.build_request("POST", token_url, json=token_request),
                )
            )
            if response.status_code != HTTPStatus.OK:
                msg = (
                    f"Management API token request failed: HTTP {response.status_code}"
                )
                raise Auth0ManagementError(
                    msg, cause=f"token_http_{response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as error:
                msg = "Management API token response is invalid"
                raise Auth0ManagementError(
                    msg, cause="token_unreadable_answer"
                ) from error
            token = payload.get("access_token") if isinstance(payload, dict) else None
            expires_in = (
                payload.get("expires_in") if isinstance(payload, dict) else None
            )
            if not isinstance(token, str) or not token:
                msg = "Management API token response is invalid"
                raise Auth0ManagementError(msg, cause="token_unreadable_answer")
            lifetime = int(expires_in) if isinstance(expires_in, int) else 0
            self._token = token
            self._expires_at = now + max(lifetime, TOKEN_REFRESH_MARGIN_SECONDS * 2)
            return token

    def _discard_token(self, token: str) -> None:
        """Forget a rejected token unless another thread already replaced it."""
        with self._lock:
            if self._token == token:
                self._token = None
                self._expires_at = 0.0

    def prepare_deletion(self) -> None:
        """Load the client secret and obtain a token before any data changes.

        Callers run this before deleting their own records, so a credential or
        Secret Manager failure stops the deletion with nothing removed.
        """
        self._access_token()

    def _delete_request(self, subject: str, token: str) -> httpx.Response:
        return self._request(
            "DELETE",
            f"{self._base_url}/api/v2/users/{quote(subject, safe='')}",
            headers={"Authorization": f"Bearer {token}"},
        )

    def delete_user(self, subject: str) -> None:
        """Delete one Auth0 user; an already-absent user counts as deleted.

        A 401 means the cached token was revoked or rotated, so it is dropped
        and the request is retried once with a fresh token.
        """
        token = self._access_token()
        response = self._delete_request(subject, token)
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            self._discard_token(token)
            response = self._delete_request(subject, self._access_token())
        if response.status_code in {200, 202, 204, 404}:
            return
        msg = f"Management API user deletion failed: HTTP {response.status_code}"
        raise Auth0ManagementError(msg, cause=f"http_{response.status_code}")

    def _search_request(
        self, http_client: httpx.Client, parameters: Mapping[str, str], token: str
    ) -> httpx.Response:
        return self._send(
            http_client,
            http_client.build_request(
                "GET",
                f"{self._base_url}/api/v2/users",
                params={**parameters, "sort": USER_SEARCH_SORT},
                headers={"Authorization": f"Bearer {token}"},
            ),
        )

    def _authorized_search(
        self, http_client: httpx.Client, parameters: Mapping[str, str]
    ) -> httpx.Response:
        """Search with the cached token; after a 401, once more with a fresh one.

        A 401 means the cached token was revoked or rotated.
        """
        token = self._access_token(http_client)
        response = self._search_request(http_client, parameters, token)
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            self._discard_token(token)
            response = self._search_request(
                http_client, parameters, self._access_token(http_client)
            )
        return response

    def _rate_limit_wait(self, response: httpx.Response) -> float | None:
        """Return the seconds a rate-limited answer asks to wait, or None.

        ``Retry-After`` gives them directly; otherwise ``X-RateLimit-Reset``
        gives the Unix time the limit resets.
        """
        retry_after = _seconds(response.headers.get("Retry-After"))
        if retry_after is not None:
            return max(0.0, retry_after)
        reset_at = _seconds(response.headers.get("X-RateLimit-Reset"))
        if reset_at is not None:
            return max(0.0, reset_at - self._clock())
        return None

    def _profile_read(
        self, send: Callable[[], httpx.Response], wait_budget: RateLimitWaitBudget
    ) -> httpx.Response:
        """Send one profile read; raise Auth0UserProfilesUnavailableError on failure.

        A rate-limited read (429) is retried once, after the wait Auth0 gives,
        when that wait fits in what is left of ``wait_budget``.
        """
        try:
            response = send()
            if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                wait = self._rate_limit_wait(response)
                if wait is not None and wait_budget.take(wait):
                    self._sleep(wait)
                    response = send()
        except Auth0ManagementError as error:
            msg = f"Auth0 user profiles are unavailable: {error.cause}"
            raise Auth0UserProfilesUnavailableError(msg, cause=error.cause) from error
        return response

    def _search_users(
        self,
        http_client: httpx.Client,
        parameters: Mapping[str, str],
        wait_budget: RateLimitWaitBudget,
    ) -> list[object]:
        """Run one user search; raise Auth0UserProfilesUnavailableError on failure.

        A rate-limited search (429) is retried once, after the wait Auth0
        gives, when that wait fits in what is left of ``wait_budget``.
        """
        response = self._profile_read(
            lambda: self._authorized_search(http_client, parameters), wait_budget
        )
        if response.status_code != HTTPStatus.OK:
            msg = f"Auth0 user profiles are unavailable: HTTP {response.status_code}"
            raise Auth0UserProfilesUnavailableError(
                msg, cause=f"http_{response.status_code}"
            )
        try:
            users = response.json()
        except ValueError as error:
            msg = "Auth0 user profiles are unavailable: the answer is not JSON"
            raise Auth0UserProfilesUnavailableError(
                msg, cause="unreadable_answer"
            ) from error
        if not isinstance(users, list):
            msg = "Auth0 user profiles are unavailable: the answer is not a list"
            raise Auth0UserProfilesUnavailableError(msg, cause="unreadable_answer")
        return users

    def read_user_profiles(
        self,
        user_ids: Iterable[str],
        *,
        wait_budget: RateLimitWaitBudget | None = None,
    ) -> dict[str, Auth0UserProfile]:
        """Return the profiles Auth0 has for these user IDs, by user ID.

        One search reads each group of at most 50 IDs, all through one HTTP
        client. IDs Auth0 doesn't know are left out. Rate-limit waits are
        spent from ``wait_budget``, else from a budget of this call's own.
        Raise Auth0UserProfilesUnavailableError when any search fails.
        """
        requested = list(dict.fromkeys(user_ids))
        profiles: dict[str, Auth0UserProfile] = {}
        if not requested:
            return profiles
        budget = RateLimitWaitBudget() if wait_budget is None else wait_budget
        with self._operation_http_client() as http_client:
            for start in range(0, len(requested), USER_SEARCH_PAGE_SIZE):
                group = requested[start : start + USER_SEARCH_PAGE_SIZE]
                query = " OR ".join(_quoted_user_id(user_id) for user_id in group)
                users = self._search_users(
                    http_client,
                    {
                        "q": f"user_id:({query})",
                        "search_engine": "v3",
                        "fields": USER_PROFILE_FIELDS,
                        "include_fields": "true",
                        "per_page": str(len(group)),
                    },
                    budget,
                )
                wanted = set(group)
                for payload in users:
                    profile = _user_profile(payload)
                    if profile is not None and profile.user_id in wanted:
                        profiles[profile.user_id] = profile
        return profiles

    def _user_request(
        self, http_client: httpx.Client, user_id: str, token: str
    ) -> httpx.Response:
        return self._send(
            http_client,
            http_client.build_request(
                "GET",
                f"{self._base_url}/api/v2/users/{quote(user_id, safe='')}",
                params={"fields": USER_PROFILE_FIELDS, "include_fields": "true"},
                headers={"Authorization": f"Bearer {token}"},
            ),
        )

    def _authorized_user_request(
        self, http_client: httpx.Client, user_id: str
    ) -> httpx.Response:
        """Read one user with the cached token; after a 401, with a new one."""
        token = self._access_token(http_client)
        response = self._user_request(http_client, user_id, token)
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            self._discard_token(token)
            response = self._user_request(
                http_client, user_id, self._access_token(http_client)
            )
        return response

    def read_user_profile(
        self, user_id: str, *, wait_budget: RateLimitWaitBudget | None = None
    ) -> Auth0UserProfile | None:
        """Return one user's profile, read by ID, or None when Auth0 has no such user.

        ``GET /api/v2/users/{id}`` is immediately consistent, so it sees a user
        who signed up or verified their email moments ago, which the search
        may not. A rate-limited read is retried once within ``wait_budget``,
        else a budget of this call's own. Raise Auth0UserProfilesUnavailableError
        when Auth0 can't answer, or answers with another user or no user.
        """
        budget = RateLimitWaitBudget() if wait_budget is None else wait_budget
        with self._operation_http_client() as http_client:
            response = self._profile_read(
                lambda: self._authorized_user_request(http_client, user_id), budget
            )
        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        if response.status_code != HTTPStatus.OK:
            msg = f"Auth0 user profiles are unavailable: HTTP {response.status_code}"
            raise Auth0UserProfilesUnavailableError(
                msg, cause=f"http_{response.status_code}"
            )
        try:
            profile = _user_profile(response.json())
        except ValueError as error:
            msg = "Auth0 user profiles are unavailable: the answer is not JSON"
            raise Auth0UserProfilesUnavailableError(
                msg, cause="unreadable_answer"
            ) from error
        if profile is None or profile.user_id != user_id:
            msg = "Auth0 user profiles are unavailable: the answer is not the user"
            raise Auth0UserProfilesUnavailableError(msg, cause="unreadable_answer")
        return profile

    def search_user_ids_by_email(
        self,
        text: str,
        *,
        match_limit: int,
        wait_budget: RateLimitWaitBudget | None = None,
    ) -> Auth0UserIdSearch:
        """Return the IDs of Auth0 users whose email contains ``text``.

        Matching ignores case, and every character of ``text`` matches
        itself. With fewer than three characters, only emails that start with
        ``text`` match. Auth0's search is eventually consistent, so a user
        created or changed moments ago may be missing. Results are read 50 a
        page, through one HTTP client, until a page is short or more than
        ``match_limit`` users have matched: at most ``match_limit // 50 + 1``
        pages. A full last page counts as more than ``match_limit``, since
        it may hide more users. Rate-limit waits are spent from
        ``wait_budget``, else from a budget of this call's own. Raise
        ValueError for a match limit outside 1 to 999 or text with ``<`` or
        ``>``, before any request, and Auth0UserProfilesUnavailableError when
        any page fails.
        """
        if not 0 < match_limit < USER_SEARCH_RESULT_LIMIT:
            msg = f"match_limit must be from 1 to {USER_SEARCH_RESULT_LIMIT - 1}"
            raise ValueError(msg)
        query = email_search_query(text)
        budget = RateLimitWaitBudget() if wait_budget is None else wait_budget
        user_ids: dict[str, None] = {}
        with self._operation_http_client() as http_client:
            for page in range(match_limit // USER_SEARCH_PAGE_SIZE + 1):
                users = self._search_users(
                    http_client,
                    {
                        "q": query,
                        "search_engine": "v3",
                        "fields": "user_id",
                        "include_fields": "true",
                        "per_page": str(USER_SEARCH_PAGE_SIZE),
                        "page": str(page),
                    },
                    budget,
                )
                for payload in users:
                    profile = _user_profile(payload)
                    if profile is not None:
                        user_ids[profile.user_id] = None
                if len(user_ids) > match_limit:
                    return Auth0UserIdSearch(user_ids=(), more_than_limit=True)
                if len(users) < USER_SEARCH_PAGE_SIZE:
                    return Auth0UserIdSearch(
                        user_ids=tuple(user_ids), more_than_limit=False
                    )
        # The last page read was full, through duplicate or ID-less entries,
        # so more users may match.
        return Auth0UserIdSearch(user_ids=(), more_than_limit=True)


_shared_clients: dict[Auth0ManagementSettings, Auth0ManagementClient] = {}
_shared_clients_lock = threading.Lock()


def _shared_client(settings: Auth0ManagementSettings) -> Auth0ManagementClient:
    """Return one process-wide client per settings so its token is reused."""
    with _shared_clients_lock:
        client = _shared_clients.get(settings)
        if client is None:
            client = Auth0ManagementClient(settings)
            _shared_clients[settings] = client
        return client


def build_auth0_user_deleter(
    environ: Mapping[str, str] | None = None,
) -> Auth0ManagementClient | None:
    """Return the deleter for the configured tenant, or ``None``.

    Every call with the same settings returns one shared client, so the
    Management API token is fetched once and reused until shortly before it
    expires. Settings are read on each call, so callers invoke this only when
    they are about to delete an account.
    """
    settings = load_auth0_management_settings(environ)
    if settings is None:
        return None
    return _shared_client(settings)


def build_auth0_user_profile_reader(
    environ: Mapping[str, str] | None = None,
) -> UserProfileReader | None:
    """Return the profile reader for the configured tenant, or ``None``.

    Callers get only the reads, never the deletion. Like the deleter, every
    call with the same settings returns one shared client and reuses its
    token; a deleter with the same settings is the same client.
    """
    settings = load_auth0_user_profile_settings(environ)
    if settings is None:
        return None
    return _shared_client(settings)
