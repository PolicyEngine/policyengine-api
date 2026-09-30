from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from flask import Flask, Response

from policyengine_api.asgi_factory import NativeRouteDependencies, create_asgi_app
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.migration_logging import (
    log_migration_request,
    register_migration_request_logging,
)
from policyengine_api.observability.identifiers import (
    OBSERVABILITY_ID_HEADER,
)
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    current_observability_id,
    current_request_id,
    start_observability_id,
)

OBSERVABILITY_ID = "00000000-0000-4000-8000-000000000123"


def _app():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/readiness-check")
    def readiness_check():
        return Response("OK", status=200, mimetype="text/plain")

    @app.route("/request-id")
    def request_id():
        return Response(current_request_id(), status=200, mimetype="text/plain")

    @app.route("/calculation")
    def calculation():
        start_observability_id()
        return Response(
            current_observability_id(),
            status=200,
            mimetype="text/plain",
        )

    register_migration_request_logging(app)
    return app


def _app_without_migration_logging():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/fallback")
    def fallback():
        return Response("fallback", status=200, mimetype="text/plain")

    return app


class _HealthySimulationGateway:
    def health_check(self) -> bool:
        return True


class _MetadataReader:
    def get_metadata(self, country_id: str):
        return {"country": country_id}


class _FailingMetadataReader:
    def get_metadata(self, country_id: str):
        raise RuntimeError("private metadata failure")


def _dependencies():
    return NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=_HealthySimulationGateway,
        metadata_reader_factory=_MetadataReader,
        specification_provider=lambda: {"openapi": "3.0.0"},
    )


def _settings(
    *,
    health=RouteImplementation.FLASK_FALLBACK,
    specification=RouteImplementation.FLASK_FALLBACK,
    metadata=RouteImplementation.FLASK_FALLBACK,
):
    return RouteImplementationSettings(
        health=health,
        specification=specification,
        metadata=metadata,
    )


def test_request_logging_includes_migration_context():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = _app().test_client().get("/readiness-check")

    assert response.status_code == 200
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["message"] == "API request served"
    assert log_payload["path"] == "/readiness-check"
    assert log_payload["status_code"] == 200
    assert log_payload["migration"]["route_group"] == "health"
    assert "api_host_backend" not in log_payload["migration"]
    assert log_payload["migration"]["route_impl"] == "flask_fallback"


def test_instrumented_flask_request_enriches_single_adapter_record():
    app = Flask(__name__)
    app.config["TESTING"] = True
    runtime = Mock()
    runtime.capture_context.return_value = {"request_id": "request-123"}

    @app.route("/<country_id>/metadata")
    def metadata(country_id):
        return Response(country_id, status=200, mimetype="text/plain")

    register_migration_request_logging(app, runtime=runtime)

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = app.test_client().get("/us/metadata")

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "request-123"
    assert runtime.set_context.call_count == 2
    runtime.set_context.assert_any_call(request_id="request-123")
    assert "X-PolicyEngine-Observability-Id" not in response.headers
    request_context = runtime.set_context.call_args.kwargs
    assert request_context["country_id"] == "us"
    assert request_context["route_group"] == "metadata"
    assert request_context["route_impl"] == "flask_fallback"
    mock_logger.log_struct.assert_not_called()


def test_observability_runtime_failure_does_not_reject_flask_request():
    app = Flask(__name__)
    runtime = Mock()
    runtime.capture_context.side_effect = RuntimeError("runtime unavailable")
    runtime.set_context.side_effect = RuntimeError("runtime unavailable")
    register_migration_request_logging(app, runtime=runtime)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    assert response.headers[REQUEST_ID_HEADER]
    assert "X-PolicyEngine-Observability-Id" not in response.headers


def test_flask_reapplies_calculation_identifier_to_server_request_span():
    app = Flask(__name__)
    runtime = Mock()
    runtime.capture_context.return_value = {"request_id": "request-123"}

    @app.get("/<country_id>/calculation")
    def calculation(country_id):
        start_observability_id()
        return {"country_id": country_id}

    register_migration_request_logging(app, runtime=runtime)

    with patch(
        "policyengine_api.observability.get_runtime",
        return_value=runtime,
    ):
        response = app.test_client().get(
            "/us/calculation",
            headers={OBSERVABILITY_ID_HEADER: OBSERVABILITY_ID},
        )

    assert response.status_code == 200
    assert response.headers[OBSERVABILITY_ID_HEADER] == OBSERVABILITY_ID
    runtime.set_context.assert_any_call(observability_id=OBSERVABILITY_ID)
    request_context = runtime.set_context.call_args.kwargs
    assert request_context["country_id"] == "us"
    assert request_context["route_group"] == "unknown"
    assert request_context["route_impl"] == "flask_fallback"
    assert request_context["observability_id"] == OBSERVABILITY_ID


def test_flask_binds_incoming_observability_id_only_when_calculation_starts():
    response = (
        _app()
        .test_client()
        .get(
            "/calculation",
            headers={OBSERVABILITY_ID_HEADER: OBSERVABILITY_ID},
        )
    )

    assert response.status_code == 200
    assert response.text == OBSERVABILITY_ID
    assert response.headers[OBSERVABILITY_ID_HEADER] == OBSERVABILITY_ID


def test_flask_does_not_echo_incoming_observability_id_on_non_calculation_route():
    response = (
        _app()
        .test_client()
        .get(
            "/request-id",
            headers={OBSERVABILITY_ID_HEADER: OBSERVABILITY_ID},
        )
    )

    assert response.status_code == 200
    assert OBSERVABILITY_ID_HEADER not in response.headers


def test_flask_preserves_policyengine_request_id_in_context_log_and_response():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = (
            _app()
            .test_client()
            .get(
                "/request-id",
                headers={REQUEST_ID_HEADER: "request-123"},
            )
        )

    assert response.status_code == 200
    assert response.text == "request-123"
    assert response.headers[REQUEST_ID_HEADER] == "request-123"
    assert mock_logger.log_struct.call_args.args[0]["request_id"] == "request-123"


def test_flask_generates_one_request_id_for_context_log_and_response():
    with (
        patch(
            "policyengine_api.request_context.uuid.uuid4",
            return_value=SimpleNamespace(hex="generated-request-id"),
        ) as generate_request_id,
        patch("policyengine_api.migration_logging.logger") as mock_logger,
    ):
        response = _app().test_client().get("/request-id")

    assert response.status_code == 200
    assert response.text == "generated-request-id"
    assert response.headers[REQUEST_ID_HEADER] == "generated-request-id"
    assert (
        mock_logger.log_struct.call_args.args[0]["request_id"] == "generated-request-id"
    )
    generate_request_id.assert_called_once_with()


def test_flask_does_not_accept_x_request_id_as_an_alias():
    with (
        patch(
            "policyengine_api.request_context.uuid.uuid4",
            return_value=SimpleNamespace(hex="generated-request-id"),
        ),
        patch("policyengine_api.migration_logging.logger") as mock_logger,
    ):
        response = (
            _app()
            .test_client()
            .get(
                "/request-id",
                headers={"X-Request-ID": "legacy-request-id"},
            )
        )

    assert response.text == "generated-request-id"
    assert response.headers[REQUEST_ID_HEADER] == "generated-request-id"
    assert (
        mock_logger.log_struct.call_args.args[0]["request_id"] == "generated-request-id"
    )


def test_asgi_generated_request_id_reaches_mounted_flask_unchanged():
    with (
        patch(
            "policyengine_api.request_context.uuid.uuid4",
            return_value=SimpleNamespace(hex="generated-request-id"),
        ) as generate_request_id,
        patch("policyengine_api.migration_logging.logger") as mock_logger,
    ):
        response = TestClient(create_asgi_app(_app())).get("/request-id")

    assert response.text == "generated-request-id"
    assert response.headers[REQUEST_ID_HEADER] == "generated-request-id"
    assert (
        mock_logger.log_struct.call_args.args[0]["request_id"] == "generated-request-id"
    )
    generate_request_id.assert_called_once_with()


def test_request_logging_failure_does_not_change_response():
    with patch(
        "policyengine_api.migration_logging.logger.log_struct",
        side_effect=RuntimeError("logging failed"),
    ):
        response = _app().test_client().get("/readiness-check")

    assert response.status_code == 200
    assert response.data == b"OK"


def test_request_logging_runs_for_asgi_fallback_routes():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(create_asgi_app(_app())).get("/readiness-check")

    assert response.status_code == 200
    assert response.content == b"OK"
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["path"] == "/readiness-check"
    assert log_payload["migration"]["route_group"] == "health"


def test_request_logging_runs_for_fastapi_native_health_routes():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(create_asgi_app(_app())).get(
            "/health",
            headers={REQUEST_ID_HEADER: "request-123"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["message"] == "API request served"
    assert log_payload["request_id"] == "request-123"
    assert log_payload["path"] == "/health"
    assert log_payload["status_code"] == 200
    assert log_payload["country_id"] is None
    assert log_payload["migration"]["route_group"] == "health"
    assert "api_host_backend" not in log_payload["migration"]
    assert log_payload["migration"]["route_impl"] == "fastapi_native"


def test_native_readiness_logs_the_implementation_that_served_it():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(
            create_asgi_app(
                _app(),
                route_settings=_settings(health=RouteImplementation.FASTAPI_NATIVE),
                dependencies=_dependencies(),
            )
        ).get("/readiness-check")

    assert response.status_code == 200
    assert mock_logger.log_struct.call_count == 1
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["path"] == "/readiness-check"
    assert log_payload["migration"]["route_group"] == "health"
    assert log_payload["migration"]["route_impl"] == "fastapi_native"


def test_native_metadata_logs_country_and_actual_implementation():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(
            create_asgi_app(
                _app_without_migration_logging(),
                route_settings=_settings(metadata=RouteImplementation.FASTAPI_NATIVE),
                dependencies=_dependencies(),
            )
        ).get("/us/metadata")

    assert response.status_code == 200
    assert mock_logger.log_struct.call_count == 1
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["path"] == "/us/metadata"
    assert log_payload["country_id"] == "us"
    assert log_payload["migration"]["route_group"] == "metadata"
    assert log_payload["migration"]["route_impl"] == "fastapi_native"


def test_v2_metadata_resource_logs_its_actual_supabase_read_source(monkeypatch):
    monkeypatch.setenv("DB_READ_METADATA", "invalid-unprefixed-setting")
    monkeypatch.setenv("DB_WRITE_METADATA", "invalid-unprefixed-setting")

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        log_migration_request(
            request_id="request-123",
            method="GET",
            path="/v2/variables",
            status_code=200,
            started_at=None,
            country_id="us",
            route_impl=RouteImplementation.FASTAPI_NATIVE,
        )

    migration_context = mock_logger.log_struct.call_args.args[0]["migration"]
    assert migration_context["route_group"] == "metadata"
    assert migration_context["route_impl"] == "fastapi_native"
    assert migration_context["db_write"] is None
    assert migration_context["db_read"] == "supabase"


def test_v2_policy_resources_log_actual_supabase_read_and_write_sources(
    monkeypatch,
):
    monkeypatch.setenv("DB_READ_POLICY", "invalid-for-native-v2")
    monkeypatch.setenv("DB_WRITE_POLICY", "invalid-for-native-v2")

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        log_migration_request(
            request_id="request-read",
            method="GET",
            path="/v2/policies",
            status_code=200,
            started_at=None,
            country_id="us",
            route_impl=RouteImplementation.FASTAPI_NATIVE,
        )
        log_migration_request(
            request_id="request-write",
            method="PATCH",
            path="/v2/user-policies/00000000-0000-0000-0000-000000000001",
            status_code=200,
            started_at=None,
            country_id="us",
            route_impl=RouteImplementation.FASTAPI_NATIVE,
        )

    read_context = mock_logger.log_struct.call_args_list[0].args[0]["migration"]
    write_context = mock_logger.log_struct.call_args_list[1].args[0]["migration"]
    assert read_context == {
        **read_context,
        "route_group": "policy",
        "route_impl": "fastapi_native",
        "db_write": None,
        "db_read": "supabase",
    }
    assert write_context == {
        **write_context,
        "route_group": "policy",
        "route_impl": "fastapi_native",
        "db_write": "supabase",
        "db_read": None,
    }


def test_v2_household_resources_log_actual_supabase_read_and_write_sources(
    monkeypatch,
):
    monkeypatch.setenv("DB_READ_HOUSEHOLD", "invalid-for-native-v2")
    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "invalid-for-native-v2")

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        log_migration_request(
            request_id="request-read",
            method="GET",
            path="/v2/households",
            status_code=200,
            started_at=None,
            country_id="us",
            route_impl=RouteImplementation.FASTAPI_NATIVE,
        )
        log_migration_request(
            request_id="request-write",
            method="PATCH",
            path="/v2/user-households/00000000-0000-0000-0000-000000000001",
            status_code=200,
            started_at=None,
            country_id="us",
            route_impl=RouteImplementation.FASTAPI_NATIVE,
        )

    read_context = mock_logger.log_struct.call_args_list[0].args[0]["migration"]
    write_context = mock_logger.log_struct.call_args_list[1].args[0]["migration"]
    assert read_context == {
        **read_context,
        "route_group": "household",
        "route_impl": "fastapi_native",
        "db_write": None,
        "db_read": "supabase",
    }
    assert write_context == {
        **write_context,
        "route_group": "household",
        "route_impl": "fastapi_native",
        "db_write": "supabase",
        "db_read": None,
    }


def test_native_route_failure_logs_country_and_actual_implementation():
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=_HealthySimulationGateway,
        metadata_reader_factory=_FailingMetadataReader,
        specification_provider=lambda: {"openapi": "3.0.0"},
    )

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(
            create_asgi_app(
                _app_without_migration_logging(),
                route_settings=_settings(metadata=RouteImplementation.FASTAPI_NATIVE),
                dependencies=dependencies,
            ),
            raise_server_exceptions=False,
        ).get("/us/metadata")

    assert response.status_code == 500
    assert mock_logger.log_struct.call_count == 1
    log_payload = mock_logger.log_struct.call_args.args[0]
    assert log_payload["path"] == "/us/metadata"
    assert log_payload["status_code"] == 500
    assert log_payload["country_id"] == "us"
    assert log_payload["migration"]["route_group"] == "metadata"
    assert log_payload["migration"]["route_impl"] == "fastapi_native"


def test_flask_hook_logs_actual_fallback_even_if_environment_says_native(
    monkeypatch,
):
    monkeypatch.setenv("ROUTE_IMPL_HEALTH", "fastapi_native")

    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(
            create_asgi_app(
                _app(),
                route_settings=_settings(health=RouteImplementation.FLASK_FALLBACK),
                dependencies=_dependencies(),
            )
        ).get("/readiness-check")

    assert response.status_code == 200
    assert mock_logger.log_struct.call_count == 1
    assert (
        mock_logger.log_struct.call_args.args[0]["migration"]["route_impl"]
        == "flask_fallback"
    )


def test_fastapi_native_response_includes_policyengine_request_id():
    with patch("policyengine_api.migration_logging.logger"):
        response = TestClient(create_asgi_app(_app())).get(
            "/health",
            headers={REQUEST_ID_HEADER: "request-123"},
        )

    assert response.headers[REQUEST_ID_HEADER] == "request-123"


def test_fastapi_native_logging_failure_does_not_change_response():
    with patch(
        "policyengine_api.migration_logging.logger.log_struct",
        side_effect=RuntimeError("logging failed"),
    ):
        response = TestClient(create_asgi_app(_app())).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_asgi_shell_does_not_log_unregistered_flask_fallback_routes():
    with patch("policyengine_api.migration_logging.logger") as mock_logger:
        response = TestClient(create_asgi_app(_app_without_migration_logging())).get(
            "/fallback"
        )

    assert response.status_code == 200
    assert response.content == b"fallback"
    mock_logger.log_struct.assert_not_called()


def test_flask_responses_omit_retired_backend_header():
    with patch("policyengine_api.migration_logging.logger"):
        response = _app().test_client().get("/readiness-check")

    assert response.status_code == 200
    assert "X-PolicyEngine-Backend" not in response.headers


def test_fastapi_native_responses_omit_retired_backend_header():
    with patch("policyengine_api.migration_logging.logger"):
        response = TestClient(create_asgi_app(_app())).get("/health")

    assert response.status_code == 200
    assert "X-PolicyEngine-Backend" not in response.headers


def test_asgi_shell_does_not_add_retired_backend_header_to_fallback():
    response = TestClient(create_asgi_app(_app_without_migration_logging())).get(
        "/fallback"
    )

    assert response.status_code == 200
    assert "X-PolicyEngine-Backend" not in response.headers
