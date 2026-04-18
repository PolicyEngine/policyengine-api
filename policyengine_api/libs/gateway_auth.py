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
from typing import Optional

import httpx


GATEWAY_AUTH_ISSUER_ENV = "GATEWAY_AUTH_ISSUER"
GATEWAY_AUTH_AUDIENCE_ENV = "GATEWAY_AUTH_AUDIENCE"
GATEWAY_AUTH_CLIENT_ID_ENV = "GATEWAY_AUTH_CLIENT_ID"
GATEWAY_AUTH_CLIENT_SECRET_ENV = "GATEWAY_AUTH_CLIENT_SECRET"

GATEWAY_AUTH_ENV_VARS = (
    GATEWAY_AUTH_ISSUER_ENV,
    GATEWAY_AUTH_AUDIENCE_ENV,
    GATEWAY_AUTH_CLIENT_ID_ENV,
    GATEWAY_AUTH_CLIENT_SECRET_ENV,
)


class GatewayAuthError(RuntimeError):
    """Raised when the gateway auth config is missing or the token fetch fails."""


def _require_all_or_none_gateway_auth_env() -> None:
    """Refuse to start when the four GATEWAY_AUTH_* env vars are partially set.

    A typo in one GH Action secret name would otherwise silently degrade to
    unauthenticated gateway calls, which is the exact scenario this module
    exists to prevent.
    """
    present = [name for name in GATEWAY_AUTH_ENV_VARS if os.environ.get(name)]
    if present and len(present) != len(GATEWAY_AUTH_ENV_VARS):
        missing = [name for name in GATEWAY_AUTH_ENV_VARS if not os.environ.get(name)]
        raise GatewayAuthError(
            "Gateway auth is partially configured: "
            f"{', '.join(present)} set but {', '.join(missing)} missing. "
            "Set all four or none."
        )


class GatewayAuthTokenProvider:
    """Fetch and cache an Auth0 ``client_credentials`` access token.

    The provider is thread-safe and refreshes the token a short window before
    its advertised expiry so concurrent workers cannot race and observe an
    expired token between validation and use. A single instance can (and
    should) be shared across many HTTP clients.
    """

    _REFRESH_MARGIN_SECONDS = 60

    def __init__(
        self,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        *,
        http_timeout: float = 10.0,
    ):
        self._issuer = (
            issuer
            if issuer is not None
            else os.environ.get(GATEWAY_AUTH_ISSUER_ENV, "")
        ).rstrip("/")
        self._audience = (
            audience
            if audience is not None
            else os.environ.get(GATEWAY_AUTH_AUDIENCE_ENV, "")
        )
        self._client_id = (
            client_id
            if client_id is not None
            else os.environ.get(GATEWAY_AUTH_CLIENT_ID_ENV, "")
        )
        self._client_secret = (
            client_secret
            if client_secret is not None
            else os.environ.get(GATEWAY_AUTH_CLIENT_SECRET_ENV, "")
        )
        self._http_timeout = http_timeout
        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        """True iff all four required env vars / kwargs were provided."""
        return all((self._issuer, self._audience, self._client_id, self._client_secret))

    def get_token(self) -> str:
        """Return a valid bearer token, fetching or refreshing as needed."""
        if not self.configured:
            raise GatewayAuthError(
                "Gateway auth not configured: set "
                f"{GATEWAY_AUTH_ISSUER_ENV}, {GATEWAY_AUTH_AUDIENCE_ENV}, "
                f"{GATEWAY_AUTH_CLIENT_ID_ENV}, and "
                f"{GATEWAY_AUTH_CLIENT_SECRET_ENV}."
            )
        with self._lock:
            now = time.time()
            if (
                self._token is None
                or now >= self._expires_at - self._REFRESH_MARGIN_SECONDS
            ):
                self._fetch_locked()
            return self._token  # type: ignore[return-value]

    def _fetch_locked(self) -> None:
        """Call Auth0's ``/oauth/token``. Caller must hold ``_lock``."""
        try:
            response = httpx.post(
                f"{self._issuer}/oauth/token",
                json={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "audience": self._audience,
                    "grant_type": "client_credentials",
                },
                timeout=self._http_timeout,
            )
        except httpx.RequestError as exc:
            raise GatewayAuthError(f"Auth0 token fetch network error: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GatewayAuthError(
                f"Auth0 token fetch failed: HTTP {response.status_code}"
            ) from exc

        data = response.json()
        token = data.get("access_token")
        if not token:
            raise GatewayAuthError("Auth0 response missing access_token")
        # Clamp expires_in so a pathological short/zero value from Auth0
        # cannot drive the refresh check into perpetual refetching under
        # concurrent load.
        raw_expires_in = data.get("expires_in")
        if raw_expires_in is None:
            raise GatewayAuthError("Auth0 response missing expires_in")
        expires_in = max(int(raw_expires_in), self._REFRESH_MARGIN_SECONDS * 2)
        self._token = token
        self._expires_at = time.time() + expires_in

    def invalidate(self) -> None:
        """Drop the cached token so the next ``get_token`` call refetches.

        Intended for recovery after a 401 from the gateway (e.g. the Auth0
        signing key rotated) rather than routine use.
        """
        with self._lock:
            self._token = None
            self._expires_at = 0.0


class GatewayBearerAuth(httpx.Auth):
    """``httpx.Auth`` adapter that attaches a refreshed bearer token per request.

    Implements httpx's two-yield retry contract: on a 401 the cached token is
    invalidated and a single retry is made with a freshly fetched token. This
    covers the common case of Auth0 rotating its JWKS while a long-lived v1
    worker holds a stale token.
    """

    def __init__(self, token_provider: GatewayAuthTokenProvider):
        self._token_provider = token_provider

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self._token_provider.get_token()}"
        response = yield request

        if response.status_code != 401:
            return

        self._token_provider.invalidate()
        request.headers["Authorization"] = f"Bearer {self._token_provider.get_token()}"
        yield request
