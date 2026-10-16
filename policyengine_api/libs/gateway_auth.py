"""Auth0 client_credentials support for outbound calls to the simulation gateway.

The simulation API gateway (``policyengine-api-v2``) gates its write and
job-status endpoints behind a bearer JWT minted by the PolicyEngine Auth0
tenant. This module fetches that token for the v1 API process, caches it in
memory, and attaches it to every outbound HTTP call via an ``httpx.Auth``
implementation.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from functools import cache
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Generator

GATEWAY_AUTH_ISSUER_ENV = "GATEWAY_AUTH_ISSUER"
GATEWAY_AUTH_AUDIENCE_ENV = "GATEWAY_AUTH_AUDIENCE"
GATEWAY_AUTH_CLIENT_ID_ENV = "GATEWAY_AUTH_CLIENT_ID"
GATEWAY_AUTH_CLIENT_SECRET_ENV = "GATEWAY_AUTH_CLIENT_SECRET"  # noqa: S105  # an environment variable name, not a secret
GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV = "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE"  # noqa: S105  # an environment variable name, not a secret
GATEWAY_AUTH_REQUIRED_ENV = "GATEWAY_AUTH_REQUIRED"

GATEWAY_AUTH_CORE_ENV_VARS = (
    GATEWAY_AUTH_ISSUER_ENV,
    GATEWAY_AUTH_AUDIENCE_ENV,
    GATEWAY_AUTH_CLIENT_ID_ENV,
)

GATEWAY_AUTH_SECRET_SOURCE_ENV_VARS = (
    GATEWAY_AUTH_CLIENT_SECRET_ENV,
    GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV,
)

GATEWAY_AUTH_ENV_VARS = (
    *GATEWAY_AUTH_CORE_ENV_VARS,
    *GATEWAY_AUTH_SECRET_SOURCE_ENV_VARS,
)


class GatewayAuthError(RuntimeError):
    """Raised when the gateway auth config is missing or the token fetch fails."""


def gateway_auth_required() -> bool:
    """Return whether ``GATEWAY_AUTH_REQUIRED`` makes missing gateway auth an error.

    Only ``1``, ``true``, ``yes`` and ``on`` (any case) enable it.
    """
    return os.environ.get(GATEWAY_AUTH_REQUIRED_ENV, "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


@cache
def _load_secret_from_secret_manager(resource_name: str) -> str:
    """Fetch one secret payload from Google Secret Manager."""
    from google.cloud import (  # noqa: PLC0415  # the Google client loads only when gateway auth reads a secret
        secretmanager,
    )

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource_name})
    return response.payload.data.decode("utf-8")


def _require_all_or_none_gateway_auth_env() -> None:
    """Refuse startup when gateway auth is partially or ambiguously configured."""
    present_core = [name for name in GATEWAY_AUTH_CORE_ENV_VARS if os.environ.get(name)]
    present_secret_sources = [
        name for name in GATEWAY_AUTH_SECRET_SOURCE_ENV_VARS if os.environ.get(name)
    ]
    if len(present_secret_sources) > 1:
        msg = (
            "Gateway auth is ambiguously configured: both "
            f"{GATEWAY_AUTH_CLIENT_SECRET_ENV} and "
            f"{GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV} are set. "
            "Set exactly one secret source."
        )
        raise GatewayAuthError(msg)
    if present_core or present_secret_sources:
        missing_core = [
            name for name in GATEWAY_AUTH_CORE_ENV_VARS if not os.environ.get(name)
        ]
        if missing_core or not present_secret_sources:
            missing = [
                *missing_core,
                *(
                    []
                    if present_secret_sources
                    else [
                        f"{GATEWAY_AUTH_CLIENT_SECRET_ENV} or "
                        f"{GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV}"
                    ]
                ),
            ]
            present = [*present_core, *present_secret_sources]
            msg = (
                "Gateway auth is partially configured: "
                f"{', '.join(present)} set but {', '.join(missing)} missing. "
                "Set issuer, audience, client ID, and exactly one secret source."
            )
            raise GatewayAuthError(msg)


@dataclass(frozen=True)
class GatewayAuthCredentials:
    """Auth0 client_credentials settings for the simulation gateway.

    A setting left None is read from its environment variable.
    """

    issuer: str | None = None
    audience: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    client_secret_resource: str | None = None


class GatewayAuthTokenProvider:
    """Fetch and cache an Auth0 client_credentials access token."""

    _REFRESH_MARGIN_SECONDS = 60

    def __init__(
        self,
        credentials: GatewayAuthCredentials | None = None,
        *,
        http_timeout: float = 10.0,
    ) -> None:
        """Read each Auth0 setting from ``credentials``, else its environment."""
        if credentials is None:
            credentials = GatewayAuthCredentials()
        self._issuer = (
            credentials.issuer
            if credentials.issuer is not None
            else os.environ.get(GATEWAY_AUTH_ISSUER_ENV, "")
        ).rstrip("/")
        self._audience = (
            credentials.audience
            if credentials.audience is not None
            else os.environ.get(GATEWAY_AUTH_AUDIENCE_ENV, "")
        )
        self._client_id = (
            credentials.client_id
            if credentials.client_id is not None
            else os.environ.get(GATEWAY_AUTH_CLIENT_ID_ENV, "")
        )
        self._client_secret = (
            credentials.client_secret
            if credentials.client_secret is not None
            else os.environ.get(GATEWAY_AUTH_CLIENT_SECRET_ENV, "")
        )
        self._client_secret_resource = (
            credentials.client_secret_resource
            if credentials.client_secret_resource is not None
            else os.environ.get(GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV, "")
        )
        self._http_timeout = http_timeout
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        """True iff all four required values were provided."""
        return all(
            (
                self._issuer,
                self._audience,
                self._client_id,
                self._client_secret or self._client_secret_resource,
            )
        )

    def get_token(self) -> str:
        """Return a valid bearer token, refreshing it when necessary."""
        if not self.configured:
            msg = (
                "Gateway auth not configured: set "
                f"{GATEWAY_AUTH_ISSUER_ENV}, {GATEWAY_AUTH_AUDIENCE_ENV}, "
                f"{GATEWAY_AUTH_CLIENT_ID_ENV}, and either "
                f"{GATEWAY_AUTH_CLIENT_SECRET_ENV} or "
                f"{GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV}."
            )
            raise GatewayAuthError(msg)

        with self._lock:
            now = time.time()
            if (
                self._token is None
                or now >= self._expires_at - self._REFRESH_MARGIN_SECONDS
            ):
                self._fetch_locked()
            return self._token  # type: ignore[return-value]

    def _fetch_locked(self) -> None:
        """Call Auth0's /oauth/token. Caller must hold _lock."""
        client_secret = self._get_client_secret_locked()
        try:
            response = httpx.post(
                f"{self._issuer}/oauth/token",
                json={
                    "client_id": self._client_id,
                    "client_secret": client_secret,
                    "audience": self._audience,
                    "grant_type": "client_credentials",
                },
                timeout=self._http_timeout,
            )
        except httpx.RequestError as exc:
            msg = f"Auth0 token fetch network error: {exc}"
            raise GatewayAuthError(msg) from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            msg = f"Auth0 token fetch failed: HTTP {response.status_code}"
            raise GatewayAuthError(msg) from exc

        data = response.json()
        token = data.get("access_token")
        if not token:
            msg = "Auth0 response missing access_token"
            raise GatewayAuthError(msg)

        raw_expires_in = data.get("expires_in")
        if raw_expires_in is None:
            msg = "Auth0 response missing expires_in"
            raise GatewayAuthError(msg)

        # Clamp pathological short expiries to avoid perpetual refetching.
        expires_in = max(int(raw_expires_in), self._REFRESH_MARGIN_SECONDS * 2)
        self._token = token
        self._expires_at = time.time() + expires_in

    def _get_client_secret_locked(self) -> str:
        """Resolve the client secret from env or Secret Manager."""
        if self._client_secret:
            return self._client_secret
        if not self._client_secret_resource:
            msg = (
                "Gateway auth client secret not configured: set "
                f"{GATEWAY_AUTH_CLIENT_SECRET_ENV} or "
                f"{GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV}."
            )
            raise GatewayAuthError(msg)
        try:
            self._client_secret = _load_secret_from_secret_manager(
                self._client_secret_resource
            )
        except Exception as exc:
            msg = (
                "Failed to load gateway auth client secret from Secret Manager "
                f"resource {self._client_secret_resource}: {exc}"
            )
            raise GatewayAuthError(msg) from exc
        if not self._client_secret:
            msg = "Secret Manager returned an empty gateway auth client secret."
            raise GatewayAuthError(msg)
        return self._client_secret

    def invalidate(self) -> None:
        """Drop the cached token so the next call refetches it."""
        with self._lock:
            self._token = None
            self._expires_at = 0.0


class GatewayBearerAuth(httpx.Auth):
    """Attach a bearer token and retry once on a 401."""

    def __init__(self, token_provider: GatewayAuthTokenProvider) -> None:
        """Authenticate requests with tokens from ``token_provider``."""
        self._token_provider = token_provider

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        """Add a bearer token; on a 401, refetch the token and resend once."""
        request.headers["Authorization"] = f"Bearer {self._token_provider.get_token()}"
        response = yield request

        if response.status_code != HTTPStatus.UNAUTHORIZED:
            return

        self._token_provider.invalidate()
        request.headers["Authorization"] = f"Bearer {self._token_provider.get_token()}"
        yield request
