"""Pin the order and content of the ASGI shell's per-request telemetry calls."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import ANY, Mock, call, patch

from fastapi.testclient import TestClient
from flask import Flask, make_response

from policyengine_api import asgi_factory
from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.observability.identifiers import OBSERVABILITY_ID_HEADER
from policyengine_api.request_context import REQUEST_ID_HEADER

OBSERVABILITY_ID = "00000000-0000-4000-8000-000000000001"


def _flask_app() -> Flask:
    app = Flask(__name__)

    @app.get("/invalid-observability-id")
    def invalid_observability_id():
        response = make_response("fallback", 200)
        response.headers[OBSERVABILITY_ID_HEADER] = "not-an-observability-id"
        return response

    return app


def _native_health_app(runtime: Mock, readiness_probe=lambda: True):
    dependencies = replace(
        asgi_factory.NativeRouteDependencies(
            readiness_probe=lambda: True,
            gateway_client_factory=lambda: None,
            metadata_reader_factory=lambda: None,
            specification_provider=dict,
        ),
        readiness_probe=readiness_probe,
    )
    return create_asgi_app(
        _flask_app(),
        route_settings=RouteImplementationSettings(
            health=RouteImplementation.FASTAPI_NATIVE,
            specification=RouteImplementation.FLASK_FALLBACK,
            metadata=RouteImplementation.FLASK_FALLBACK,
        ),
        dependencies=dependencies,
        observability_runtime=runtime,
    )


def test_native_request_calls_the_runtime_and_logger_in_a_fixed_order() -> None:
    timeline = Mock()
    timeline.runtime.begin_request.return_value = "runtime-request-id"
    timeline.runtime.response_headers.return_value = {"x-trace": "trace-1"}

    with (
        patch.object(asgi_factory, "log_migration_request", timeline.log),
        patch.object(
            asgi_factory, "current_observability_id", return_value=OBSERVABILITY_ID
        ),
    ):
        response = TestClient(_native_health_app(timeline.runtime)).get(
            "/readiness-check?country_id=uk",
            headers={REQUEST_ID_HEADER: "incoming-request-id"},
        )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "runtime-request-id"
    assert response.headers[OBSERVABILITY_ID_HEADER] == OBSERVABILITY_ID
    assert response.headers["x-trace"] == "trace-1"
    begin_request = timeline.runtime.begin_request.call_args
    assert begin_request.kwargs["headers"][REQUEST_ID_HEADER] == "incoming-request-id"
    assert timeline.mock_calls == [
        call.runtime.begin_request(headers=ANY, method="GET", route="/readiness-check"),
        call.runtime.set_context(request_id="runtime-request-id"),
        call.runtime.set_context(observability_id=OBSERVABILITY_ID),
        call.runtime.response_headers(),
        call.log(
            request_id="runtime-request-id",
            method="GET",
            path="/readiness-check",
            status_code=200,
            started_at=ANY,
            country_id="uk",
            route_impl=RouteImplementation.FASTAPI_NATIVE,
        ),
        call.runtime.update_request_route("/readiness-check"),
        call.runtime.update_request_status(200),
        call.runtime.end_request(status_code=200, error=None),
    ]


def test_native_request_keeps_its_id_when_the_runtime_assigns_none() -> None:
    runtime = Mock()
    runtime.begin_request.return_value = ""
    runtime.response_headers.return_value = {}

    with patch.object(asgi_factory, "log_migration_request") as log_request:
        response = TestClient(_native_health_app(runtime)).get(
            "/readiness-check",
            headers={REQUEST_ID_HEADER: "incoming-request-id"},
        )

    assert response.headers[REQUEST_ID_HEADER] == "incoming-request-id"
    runtime.set_context.assert_called_once_with(request_id="incoming-request-id")
    assert log_request.call_args.kwargs["request_id"] == "incoming-request-id"
    assert log_request.call_args.kwargs["country_id"] is None


def test_failing_native_route_logs_and_finishes_as_a_server_error() -> None:
    timeline = Mock()
    timeline.runtime.begin_request.return_value = None
    route_error = RuntimeError("probe failed")

    def failing_probe() -> bool:
        raise route_error

    with patch.object(asgi_factory, "log_migration_request", timeline.log):
        response = TestClient(
            _native_health_app(timeline.runtime, readiness_probe=failing_probe),
            raise_server_exceptions=False,
        ).get("/readiness-check", headers={REQUEST_ID_HEADER: "failed-request"})

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers[REQUEST_ID_HEADER] == "failed-request"
    assert timeline.mock_calls == [
        call.runtime.begin_request(headers=ANY, method="GET", route="/readiness-check"),
        call.runtime.set_context(request_id="failed-request"),
        call.log(
            request_id="failed-request",
            method="GET",
            path="/readiness-check",
            status_code=500,
            started_at=ANY,
            country_id=None,
            route_impl=RouteImplementation.FASTAPI_NATIVE,
        ),
        call.runtime.update_request_route("/readiness-check"),
        call.runtime.update_request_status(500),
        call.runtime.end_request(status_code=500, error=route_error),
    ]


def test_native_request_survives_a_failing_observability_context_update() -> None:
    runtime = Mock()
    runtime.begin_request.return_value = None
    runtime.response_headers.return_value = {}
    runtime.set_context.side_effect = RuntimeError("context unavailable")

    with (
        patch.object(asgi_factory, "log_migration_request", side_effect=OSError),
        patch.object(
            asgi_factory, "current_observability_id", return_value=OBSERVABILITY_ID
        ),
    ):
        response = TestClient(_native_health_app(runtime)).get("/readiness-check")

    assert response.status_code == 200
    assert response.headers[OBSERVABILITY_ID_HEADER] == OBSERVABILITY_ID
    runtime.end_request.assert_called_once_with(status_code=200, error=None)


def test_fallback_response_drops_an_invalid_observability_id_header() -> None:
    runtime = Mock()

    response = TestClient(_native_health_app(runtime)).get(
        "/invalid-observability-id",
        headers={REQUEST_ID_HEADER: "fallback-request"},
    )

    assert response.status_code == 200
    assert response.text == "fallback"
    assert OBSERVABILITY_ID_HEADER not in response.headers
    assert response.headers[REQUEST_ID_HEADER] == "fallback-request"
    assert runtime.mock_calls == []


def test_shutdown_callback_runs_once_when_the_lifespan_ends() -> None:
    shutdown = Mock()
    app = create_asgi_app(_flask_app(), shutdown_callback=shutdown)

    with TestClient(app):
        shutdown.assert_not_called()

    shutdown.assert_called_once_with()
