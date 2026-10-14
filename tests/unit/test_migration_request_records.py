"""Pin the migration request records, route groups and explicit database sources."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from flask import Flask, Response

from policyengine_api.migration_flags import (
    ExplicitDatabaseSources,
    RouteImplementation,
    get_migration_context,
    get_migration_log_context,
    infer_route_group,
)
from policyengine_api.migration_logging import (
    ServedRequest,
    log_migration_request,
    register_migration_request_logging,
)
from policyengine_api.observability.identifiers import OBSERVABILITY_ID_HEADER
from policyengine_api.request_context import REQUEST_ID_HEADER

MIGRATION_ENVIRONMENT = (
    "ROUTE_IMPL_HEALTH",
    "ROUTE_IMPL_POLICY",
    "ROUTE_IMPL_METADATA",
    "DB_READ_POLICY",
    "DB_WRITE_POLICY",
    "DB_READ_METADATA",
    "DB_WRITE_METADATA",
    "SIM_ENTRYPOINT",
)


@pytest.fixture(autouse=True)
def default_migration_flags(monkeypatch) -> None:
    for name in MIGRATION_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("path", "route_group"),
    [
        ("", "home"),
        ("/", "home"),
        ("//", "home"),
        ("/health", "health"),
        ("/liveness-check", "health"),
        ("/specification", "specification"),
        ("/v2/openapi.json", "specification"),
        ("/health/extra", "health"),
        ("/us/policy/1", "policy"),
        ("/us/unknown/policy", "unknown"),
        ("/v2/policies", "policy"),
        ("/v2/us/policy", "policy"),
        ("/v3/us/policy", "unknown"),
        ("/v2", "unknown"),
        ("/v2/us", "unknown"),
        ("/policy", "policy"),
    ],
)
def test_route_groups_follow_exact_paths_then_leading_segments(
    path: str,
    route_group: str,
) -> None:
    assert infer_route_group(path) == route_group


def test_explicit_database_sources_replace_the_configured_sources() -> None:
    context = get_migration_context(
        "policy",
        route_impl=RouteImplementation.FASTAPI_NATIVE,
        explicit_db_sources=ExplicitDatabaseSources(
            db_write_source="supabase", db_read_source=None
        ),
    )

    assert context.to_log_dict() == {
        "route_group": "policy",
        "route_impl": "fastapi_native",
        "db_entity": "policy",
        "db_write": "supabase",
        "db_read": None,
        "sim_flow": None,
        "sim_entrypoint": "old_gateway_direct",
        "sim_compute": None,
    }


def test_invalid_explicit_write_source_is_reported_before_the_read_source() -> None:
    with pytest.raises(
        ValueError, match=r"^invalid explicit database write source 'bad-write'$"
    ):
        get_migration_context(
            "policy",
            explicit_db_sources=ExplicitDatabaseSources(
                db_write_source="bad-write", db_read_source="bad-read"
            ),
        )


def test_invalid_flags_become_a_log_context_error_instead_of_raising(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "invalid-source")

    assert get_migration_log_context("policy") == {
        "route_group": "policy",
        "migration_flag_error": (
            "DB_WRITE_POLICY='invalid-source' is invalid; expected one of: "
            "cloud_sql, dual_write, supabase"
        ),
    }
    assert get_migration_log_context(
        "policy",
        explicit_db_sources=ExplicitDatabaseSources(db_write_source="unknown"),
    ) == {
        "route_group": "policy",
        "migration_flag_error": "invalid explicit database write source 'unknown'",
    }


@pytest.mark.parametrize(
    ("status_code", "severity"), [(200, "INFO"), (499, "INFO"), (500, "ERROR")]
)
def test_request_record_has_a_fixed_shape_and_severity(
    status_code: int,
    severity: str,
) -> None:
    with patch("policyengine_api.migration_logging.logger") as logger:
        log_migration_request(
            ServedRequest(
                request_id="request-1",
                method="GET",
                path="/us/policy/3",
                status_code=status_code,
                started_at=None,
                country_id="us",
                route_impl=RouteImplementation.FLASK_FALLBACK,
            )
        )

    assert logger.log_struct.call_args.kwargs == {"severity": severity}
    record = logger.log_struct.call_args.args[0]
    assert list(record) == [
        "message",
        "request_id",
        "method",
        "path",
        "status_code",
        "latency_ms",
        "country_id",
        "migration",
    ]
    assert record == {
        "message": "API request served",
        "request_id": "request-1",
        "method": "GET",
        "path": "/us/policy/3",
        "status_code": status_code,
        "latency_ms": None,
        "country_id": "us",
        "migration": {
            "route_group": "policy",
            "route_impl": "flask_fallback",
            "db_entity": "policy",
            "db_write": "cloud_sql",
            "db_read": "cloud_sql",
            "sim_flow": None,
            "sim_entrypoint": "old_gateway_direct",
            "sim_compute": None,
        },
    }


def test_request_record_reports_latency_from_its_start_time() -> None:
    with (
        patch("policyengine_api.migration_logging.logger") as logger,
        patch("policyengine_api.migration_logging.time.time", return_value=12.5),
    ):
        log_migration_request(
            ServedRequest(
                request_id=None,
                method="POST",
                path="/v2/user-policies",
                status_code=201,
                started_at=10.0,
            )
        )

    record = logger.log_struct.call_args.args[0]
    assert record["latency_ms"] == 2500.0
    assert record["country_id"] is None
    assert record["migration"]["db_write"] == "supabase"
    assert record["migration"]["db_read"] is None
    assert record["migration"]["route_impl"] == "flask_fallback"


def _flask_app(runtime: Mock | None = None) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/<country_id>/policy/<int:policy_id>")
    def policy(country_id: str, policy_id: int) -> Response:
        return Response(f"{country_id}:{policy_id}", status=200)

    @app.route("/plain")
    def plain() -> Response:
        return Response("plain", status=200)

    register_migration_request_logging(app, runtime=runtime)
    return app


def test_unparameterized_flask_route_logs_without_a_country() -> None:
    with patch("policyengine_api.migration_logging.logger") as logger:
        response = _flask_app().test_client().get("/plain")

    assert response.status_code == 200
    record = logger.log_struct.call_args.args[0]
    assert record["country_id"] is None
    assert record["path"] == "/plain"
    assert response.headers[REQUEST_ID_HEADER] == record["request_id"]


def test_instrumented_flask_route_sets_the_runtime_context() -> None:
    runtime = Mock()
    runtime.capture_context.return_value = {"request_id": "captured-id"}

    with patch("policyengine_api.migration_logging.logger") as logger:
        response = (
            _flask_app(runtime)
            .test_client()
            .get("/uk/policy/9", headers={REQUEST_ID_HEADER: "ignored-header"})
        )

    assert response.headers[REQUEST_ID_HEADER] == "captured-id"
    assert OBSERVABILITY_ID_HEADER not in response.headers
    logger.log_struct.assert_not_called()
    assert runtime.set_context.call_args_list[0].kwargs == {"request_id": "captured-id"}
    assert runtime.set_context.call_args_list[1].kwargs == {
        "country_id": "uk",
        "route_group": "policy",
        "route_impl": "flask_fallback",
        "db_entity": "policy",
        "db_write": "cloud_sql",
        "db_read": "cloud_sql",
        "sim_flow": None,
        "sim_entrypoint": "old_gateway_direct",
        "sim_compute": None,
    }


def test_runtime_capture_failure_falls_back_to_the_request_header() -> None:
    runtime = Mock()
    runtime.capture_context.side_effect = RuntimeError("capture unavailable")
    runtime.set_context.side_effect = RuntimeError("context unavailable")

    response = (
        _flask_app(runtime)
        .test_client()
        .get("/plain", headers={REQUEST_ID_HEADER: "header-id"})
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "header-id"


def test_logging_failures_never_replace_the_response() -> None:
    app = _flask_app()

    with (
        patch(
            "policyengine_api.migration_logging.log_migration_request",
            side_effect=RuntimeError("logging unavailable"),
        ),
        patch.object(
            app.logger, "exception", side_effect=RuntimeError("logger unavailable")
        ) as log_exception,
    ):
        response = app.test_client().get("/us/policy/1")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "us:1"
    log_exception.assert_called_once_with("Failed to log migration request context")
