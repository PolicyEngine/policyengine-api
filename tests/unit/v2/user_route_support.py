"""Shared helpers for signed-in user route tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from flask import Flask, jsonify

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.identity.types import (
    AccountPrincipal,
    UnauthenticatedPrincipal,
    UserPrincipal,
)


ISSUER = "https://auth.example.test/"
PRINCIPAL = UserPrincipal(issuer=ISSUER, subject="google-oauth2|1234")
BROWSER_USER_ID = UUID("6f1c2a4e-8b3d-4c5e-9a7f-1e2d3c4b5a69")
UNAUTHENTICATED_PRINCIPAL = UnauthenticatedPrincipal(user_id=BROWSER_USER_ID)
OWNER_ID = UUID("00000000-0000-0000-0000-000000000070")
CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def signed_in_user() -> UserPrincipal:
    return PRINCIPAL


def signed_out_browser() -> UnauthenticatedPrincipal:
    return UNAUTHENTICATED_PRINCIPAL


def user_route_client(
    *,
    require_user: Callable[..., AccountPrincipal] | None = signed_in_user,
    **service_factories: Any,
) -> tuple[TestClient, dict[str, int]]:
    """Build the ASGI app with fake services and an injected principal.

    Passing ``require_user=None`` keeps the fail-closed default authenticator.
    """

    flask_calls = {"count": 0}
    flask_app = Flask(__name__)

    @flask_app.route("/<path:resource>", methods=["GET", "POST", "PATCH", "DELETE"])
    def fallback(resource: str):
        flask_calls["count"] += 1
        return jsonify({"source": "flask", "resource": resource})

    overrides: dict[str, Any] = dict(service_factories)
    if require_user is not None:
        overrides["require_user"] = require_user
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=lambda: {},
        **overrides,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return (
        TestClient(
            create_asgi_app(
                flask_app,
                dependencies=dependencies,
                route_settings=settings,
            ),
            raise_server_exceptions=False,
        ),
        flask_calls,
    )


class RecordingService:
    """Record calls; return ``next_result`` or raise ``error`` for any method."""

    def __init__(self, next_result: Any = None) -> None:
        self.error: Exception | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.next_result = next_result

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)

        def method(**kwargs: Any) -> Any:
            self.calls.append((name, kwargs))
            if self.error is not None:
                raise self.error
            if callable(self.next_result):
                return self.next_result(name, kwargs)
            return self.next_result

        return method
