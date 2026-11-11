"""Optional Auth0 Management API access for account deletion and user profiles.

Two settings groups each configure one Management API machine-to-machine
client, and both use the same client code, token cache and secret handling:

- ``AUTH0_MANAGEMENT_*``: ``DELETE /v2/me`` removes the Auth0 user only when a
  client with the ``delete:users`` permission is configured. Without it,
  account deletion removes only Public API data and logs that the Auth0
  deletion was skipped. Deployments allow it in production only.
- ``AUTH0_USER_PROFILES_*``: the admin user routes read users' emails and
  names from Auth0 only when a client with the ``read:users`` permission is
  configured; nothing they read is stored. Deployments allow it in staging
  and production.

Each group is all-or-none: a domain, a client ID, and exactly one
client-secret source (a direct value or a Secret Manager resource, matching
the gateway-auth pattern). The domain must be the tenant's canonical Auth0
domain (for example ``policyengine.us.auth0.com``): the Management API
audience is not served on custom domains. This module never logs, or puts in
an error message, an email, a subject, a token or a secret.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from functools import cache
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

AUTH0_MANAGEMENT_DOMAIN_ENV = "AUTH0_MANAGEMENT_DOMAIN"
AUTH0_MANAGEMENT_CLIENT_ID_ENV = "AUTH0_MANAGEMENT_CLIENT_ID"
AUTH0_MANAGEMENT_CLIENT_SECRET_ENV = "AUTH0_MANAGEMENT_CLIENT_SECRET"  # noqa: S105  # an environment variable name, not a secret
AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV = "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE"  # noqa: S105  # an environment variable name, not a secret
AUTH0_MANAGEMENT_ENV_VARS = (
    AUTH0_MANAGEMENT_DOMAIN_ENV,
    AUTH0_MANAGEMENT_CLIENT_ID_ENV,
    AUTH0_MANAGEMENT_CLIENT_SECRET_ENV,
    AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV,
)
DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
SECRET_RESOURCE_PATTERN = re.compile(r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$")
HTTP_TIMEOUT_SECONDS = 10.0
TOKEN_REFRESH_MARGIN_SECONDS = 60

# Auth0's user search (search engine v3) answers at most 50 users a page on
# its public cloud, and at most 1,000 results for one query.
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


@dataclass(frozen=True)
class Auth0ClientSettingNames:
    """The environment variables that configure one Management API client."""

    prefix: str
    # The configuration error's opening words when the group is incomplete.
    incomplete_message: str

    @property
    def domain(self) -> str:
        """The tenant's canonical domain."""
        return f"{self.prefix}_DOMAIN"

    @property
    def client_id(self) -> str:
        """The machine-to-machine client's ID."""
        return f"{self.prefix}_CLIENT_ID"

    @property
    def client_secret(self) -> str:
        """The client secret itself, for local use."""
        return f"{self.prefix}_CLIENT_SECRET"

    @property
    def client_secret_resource(self) -> str:
        """The Secret Manager version that holds the client secret."""
        return f"{self.prefix}_CLIENT_SECRET_RESOURCE"

    @property
    def names(self) -> tuple[str, str, str, str]:
        """Every environment variable of the group."""
        return (
            self.domain,
            self.client_id,
            self.client_secret,
            self.client_secret_resource,
        )


AUTH0_MANAGEMENT_SETTING_NAMES = Auth0ClientSettingNames(
    prefix="AUTH0_MANAGEMENT",
    incomplete_message="Auth0 Management API deletion is partially configured",
)
AUTH0_USER_PROFILE_SETTING_NAMES = Auth0ClientSettingNames(
    prefix="AUTH0_USER_PROFILES",
    incomplete_message="Auth0 user profile reads are partially configured",
)
AUTH0_USER_PROFILE_ENV_VARS = AUTH0_USER_PROFILE_SETTING_NAMES.names


class Auth0ManagementConfigurationError(RuntimeError):
    """Raised when the optional Management API settings are incomplete."""


class Auth0ManagementError(RuntimeError):
    """Raised when the Management API rejects or fails a request."""


class Auth0UserProfilesUnavailableError(Auth0ManagementError):
    """Raised when users' profiles can't be read: any failure of a profile read.

    Timeouts, connection errors, a refused or failed token request, a missing
    ``read:users`` permission (403), rate limiting (429), server errors (5xx)
    and an answer that isn't a list of users all raise it. The message names
    at most an HTTP status or an error type.
    """


@dataclass(frozen=True)
class Auth0ManagementSettings:
    """Validated Management API settings for one Auth0 tenant.

    Exactly one of ``client_secret`` and ``client_secret_resource`` (a Secret
    Manager version name) is set. The secret is kept out of ``repr``, and equal
    settings share one client, so its token is reused.
    """

    domain: str
    client_id: str
    client_secret: str = field(default="", repr=False)
    client_secret_resource: str = ""


@dataclass(frozen=True)
class Auth0UserProfile:
    """What the admin routes read about one Auth0 user; never stored.

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
    """The Auth0 user IDs an email search found, in Auth0's order.

    ``limit_reached`` is true when the search stopped at Auth0's 1,000-result
    limit, so more users may match.
    """

    user_ids: tuple[str, ...]
    limit_reached: bool


def _load_client_settings(
    names: Auth0ClientSettingNames, environ: Mapping[str, str] | None
) -> Auth0ManagementSettings | None:
    """Return one group's complete settings, or ``None`` when it is absent."""
    values = os.environ if environ is None else environ
    domain = values.get(names.domain, "").strip()
    client_id = values.get(names.client_id, "").strip()
    client_secret = values.get(names.client_secret, "").strip()
    secret_resource = values.get(names.client_secret_resource, "").strip()
    if not any((domain, client_id, client_secret, secret_resource)):
        return None
    if client_secret and secret_resource:
        msg = (
            f"Set exactly one of {names.client_secret} or "
            f"{names.client_secret_resource}"
        )
        raise Auth0ManagementConfigurationError(msg)
    if not domain or not client_id or not (client_secret or secret_resource):
        msg = (
            f"{names.incomplete_message}: set {names.domain}, "
            f"{names.client_id}, and exactly one client-secret source"
        )
        raise Auth0ManagementConfigurationError(msg)
    if DOMAIN_PATTERN.fullmatch(domain) is None:
        msg = f"{names.domain} must be a bare host name"
        raise Auth0ManagementConfigurationError(msg)
    if secret_resource and SECRET_RESOURCE_PATTERN.fullmatch(secret_resource) is None:
        msg = f"{names.client_secret_resource} is invalid"
        raise Auth0ManagementConfigurationError(msg)
    return Auth0ManagementSettings(
        domain=domain,
        client_id=client_id,
        client_secret=client_secret,
        client_secret_resource=secret_resource,
    )


def load_auth0_management_settings(
    environ: Mapping[str, str] | None = None,
) -> Auth0ManagementSettings | None:
    """Return complete account-deletion settings, or ``None`` when absent."""
    return _load_client_settings(AUTH0_MANAGEMENT_SETTING_NAMES, environ)


def load_auth0_user_profile_settings(
    environ: Mapping[str, str] | None = None,
) -> Auth0ManagementSettings | None:
    """Return complete user-profile settings, or ``None`` when absent."""
    return _load_client_settings(AUTH0_USER_PROFILE_SETTING_NAMES, environ)


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
    """
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
    """Read one user of a search answer, or ``None`` when it has no user ID."""
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
    ) -> None:
        """Use ``settings`` for the tenant and client credentials.

        ``http_client`` replaces the per-request client (tests pass a mock
        transport), and ``secret_loader`` reads ``client_secret_resource`` when
        no direct secret is set.
        """
        self._settings = settings
        self._http_client = http_client
        self._secret_loader = secret_loader
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
            raise Auth0ManagementError(msg) from error
        if not secret:
            msg = "the Management API client secret is empty"
            raise Auth0ManagementError(msg)
        return secret

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        try:
            if self._http_client is not None:
                return self._http_client.request(method, url, **kwargs)  # type: ignore[arg-type]
            with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
                return client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as error:
            msg = f"Management API request failed: {type(error).__name__}"
            raise Auth0ManagementError(msg) from error

    def _access_token(self) -> str:
        with self._lock:
            now = time.time()
            if (
                self._token is not None
                and now < self._expires_at - TOKEN_REFRESH_MARGIN_SECONDS
            ):
                return self._token
            response = self._request(
                "POST",
                f"{self._base_url}/oauth/token",
                json={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.client_id,
                    "client_secret": self._client_secret(),
                    "audience": f"{self._base_url}/api/v2/",
                },
            )
            if response.status_code != HTTPStatus.OK:
                msg = (
                    f"Management API token request failed: HTTP {response.status_code}"
                )
                raise Auth0ManagementError(msg)
            payload = response.json()
            token = payload.get("access_token") if isinstance(payload, dict) else None
            expires_in = (
                payload.get("expires_in") if isinstance(payload, dict) else None
            )
            if not isinstance(token, str) or not token:
                msg = "Management API token response is invalid"
                raise Auth0ManagementError(msg)
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
        raise Auth0ManagementError(msg)

    def _search_request(
        self, parameters: Mapping[str, str], token: str
    ) -> httpx.Response:
        return self._request(
            "GET",
            f"{self._base_url}/api/v2/users",
            params=dict(parameters),
            headers={"Authorization": f"Bearer {token}"},
        )

    def _search_users(self, parameters: Mapping[str, str]) -> list[object]:
        """Run one user search; raise Auth0UserProfilesUnavailableError on failure.

        A 401 means the cached token was revoked or rotated, so it is dropped
        and the search is retried once with a fresh token.
        """
        try:
            token = self._access_token()
            response = self._search_request(parameters, token)
            if response.status_code == HTTPStatus.UNAUTHORIZED:
                self._discard_token(token)
                response = self._search_request(parameters, self._access_token())
        except Auth0UserProfilesUnavailableError:
            raise
        except Auth0ManagementError as error:
            msg = f"Auth0 user profiles are unavailable: {type(error).__name__}"
            raise Auth0UserProfilesUnavailableError(msg) from error
        if response.status_code != HTTPStatus.OK:
            msg = f"Auth0 user profiles are unavailable: HTTP {response.status_code}"
            raise Auth0UserProfilesUnavailableError(msg)
        try:
            users = response.json()
        except ValueError as error:
            msg = "Auth0 user profiles are unavailable: the answer is not JSON"
            raise Auth0UserProfilesUnavailableError(msg) from error
        if not isinstance(users, list):
            msg = "Auth0 user profiles are unavailable: the answer is not a list"
            raise Auth0UserProfilesUnavailableError(msg)
        return users

    def read_user_profiles(
        self, user_ids: Iterable[str]
    ) -> dict[str, Auth0UserProfile]:
        """Return the profiles Auth0 has for these user IDs, by user ID.

        One search reads each group of at most 50 IDs. IDs Auth0 doesn't know
        are left out. Raise Auth0UserProfilesUnavailableError when any search
        fails.
        """
        requested = list(dict.fromkeys(user_ids))
        profiles: dict[str, Auth0UserProfile] = {}
        for start in range(0, len(requested), USER_SEARCH_PAGE_SIZE):
            group = requested[start : start + USER_SEARCH_PAGE_SIZE]
            query = " OR ".join(_quoted_user_id(user_id) for user_id in group)
            users = self._search_users(
                {
                    "q": f"user_id:({query})",
                    "search_engine": "v3",
                    "fields": USER_PROFILE_FIELDS,
                    "include_fields": "true",
                    "per_page": str(len(group)),
                }
            )
            wanted = set(group)
            for payload in users:
                profile = _user_profile(payload)
                if profile is not None and profile.user_id in wanted:
                    profiles[profile.user_id] = profile
        return profiles

    def search_user_ids_by_email(self, text: str) -> Auth0UserIdSearch:
        """Return the IDs of Auth0 users whose email contains ``text``.

        Matching ignores case, and every character of ``text`` matches
        itself. With fewer than three characters, only emails that start with
        ``text`` match. Auth0's search is eventually consistent, so a user
        created or changed moments ago may be missing. Results are read 50 a
        page, up to Auth0's 1,000-result limit. Raise
        Auth0UserProfilesUnavailableError when any page fails.
        """
        query = email_search_query(text)
        user_ids: list[str] = []
        for page in range(USER_SEARCH_RESULT_LIMIT // USER_SEARCH_PAGE_SIZE):
            users = self._search_users(
                {
                    "q": query,
                    "search_engine": "v3",
                    "fields": "user_id",
                    "include_fields": "true",
                    "per_page": str(USER_SEARCH_PAGE_SIZE),
                    "page": str(page),
                }
            )
            for payload in users:
                profile = _user_profile(payload)
                if profile is not None:
                    user_ids.append(profile.user_id)
            if len(users) < USER_SEARCH_PAGE_SIZE:
                return Auth0UserIdSearch(
                    user_ids=tuple(dict.fromkeys(user_ids)), limit_reached=False
                )
        return Auth0UserIdSearch(
            user_ids=tuple(dict.fromkeys(user_ids)), limit_reached=True
        )


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
) -> Auth0ManagementClient | None:
    """Return the profile reader for the configured tenant, or ``None``.

    Like the deleter, every call with the same settings returns one shared
    client and reuses its token; a deleter with the same settings is the same
    client.
    """
    settings = load_auth0_user_profile_settings(environ)
    if settings is None:
        return None
    return _shared_client(settings)
