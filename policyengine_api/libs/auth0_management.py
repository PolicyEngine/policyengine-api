"""Optional Auth0 Management API access for account deletion.

``DELETE /v2/me`` removes the Auth0 user only when a Management API
machine-to-machine client with the ``delete:users`` permission is configured.
The configuration is all-or-none: a domain, a client ID, and exactly one
client-secret source (a direct value or a Secret Manager resource, matching
the gateway-auth pattern). Without it, account deletion removes only Public
API data and logs that the Auth0 deletion was skipped.

The domain must be the tenant's canonical Auth0 domain (for example
``policyengine.us.auth0.com``): the Management API audience is not served on
custom domains. This module never logs a subject, token, or secret.
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
    from collections.abc import Callable, Mapping

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


class Auth0ManagementConfigurationError(RuntimeError):
    """Raised when the optional Management API settings are incomplete."""


class Auth0ManagementError(RuntimeError):
    """Raised when the Management API rejects or fails a request."""


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


def load_auth0_management_settings(
    environ: Mapping[str, str] | None = None,
) -> Auth0ManagementSettings | None:
    """Return complete Management API settings, or ``None`` when absent."""
    values = os.environ if environ is None else environ
    domain = values.get(AUTH0_MANAGEMENT_DOMAIN_ENV, "").strip()
    client_id = values.get(AUTH0_MANAGEMENT_CLIENT_ID_ENV, "").strip()
    client_secret = values.get(AUTH0_MANAGEMENT_CLIENT_SECRET_ENV, "").strip()
    secret_resource = values.get(
        AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV, ""
    ).strip()
    if not any((domain, client_id, client_secret, secret_resource)):
        return None
    if client_secret and secret_resource:
        msg = (
            f"Set exactly one of {AUTH0_MANAGEMENT_CLIENT_SECRET_ENV} or "
            f"{AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV}"
        )
        raise Auth0ManagementConfigurationError(msg)
    if not domain or not client_id or not (client_secret or secret_resource):
        msg = (
            "Auth0 Management API deletion is partially configured: set "
            f"{AUTH0_MANAGEMENT_DOMAIN_ENV}, {AUTH0_MANAGEMENT_CLIENT_ID_ENV}, and "
            "exactly one client-secret source"
        )
        raise Auth0ManagementConfigurationError(msg)
    if DOMAIN_PATTERN.fullmatch(domain) is None:
        msg = f"{AUTH0_MANAGEMENT_DOMAIN_ENV} must be a bare host name"
        raise Auth0ManagementConfigurationError(msg)
    if secret_resource and SECRET_RESOURCE_PATTERN.fullmatch(secret_resource) is None:
        msg = f"{AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV} is invalid"
        raise Auth0ManagementConfigurationError(msg)
    return Auth0ManagementSettings(
        domain=domain,
        client_id=client_id,
        client_secret=client_secret,
        client_secret_resource=secret_resource,
    )


@cache
def _load_secret_from_secret_manager(resource_name: str) -> str:
    from google.cloud import (  # noqa: PLC0415  # the Google client loads only when Auth0 Management reads a secret
        secretmanager,
    )

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource_name})
    return response.payload.data.decode("utf-8")


class Auth0ManagementClient:
    """Delete Auth0 users through a cached client-credentials token."""

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
