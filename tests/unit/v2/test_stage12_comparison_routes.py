"""Internal HTTP boundary tests for canonical Stage 12 persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from flask import Flask, jsonify

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.v2.comparison_runs import auth
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportPersistenceResult,
    ComparisonReportRecord,
    ComparisonSimulationPersistenceResult,
    ComparisonSimulationRecord,
)
from policyengine_api.services.v2.comparison_runs.validators import (
    ComparisonRunNotFoundError,
)


NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)
EVALUATION_ID = UUID("00000000-0000-4000-8000-000000000001")
SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000002")
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _report(**changes: object) -> ComparisonReportRecord:
    fields: dict[str, object] = {
        "evaluation_id": EVALUATION_ID,
        "status": "pending",
        "aggregation_status": "not_started",
        "environment": "staging",
        "calculation_flow": "economy",
        "originating_request_id": "request-1",
        "production_identity": "production-job-1",
        "incumbent_execution_id": "production-job-1",
        "worker_version": "5.2.0",
        "modal_application": "policyengine-v2-worker-5-2-0",
        "report_coordinator_callable": "coordinate_report",
        "version_manifest_sha256": DIGEST_A,
        "policyengine_version": "5.2.0",
        "country_package_name": "policyengine-us",
        "country_package_version": "1.900.0",
        "country": "us",
        "dataset_identity": "populace_us_2024",
        "dataset_uri": "hf://policyengine/populace-us/data.h5@revision",
        "data_package_name": "policyengine-us-data",
        "data_package_version": "1.0.0",
        "data_artifact_revision": "revision",
        "created_at": NOW,
        "updated_at": NOW,
        "retention_expires_at": NOW + timedelta(days=30),
    }
    fields.update(changes)
    return ComparisonReportRecord.model_validate(fields)


def _simulation(**changes: object) -> ComparisonSimulationRecord:
    fields: dict[str, object] = {
        "simulation_execution_id": SIMULATION_ID,
        "evaluation_id": EVALUATION_ID,
        "role": "baseline",
        "input_sha256": DIGEST_B,
        "worker_version": "5.2.0",
        "modal_application": "policyengine-v2-worker-5-2-0",
        "simulation_callable": "run_single_simulation_us",
        "version_manifest_sha256": DIGEST_A,
        "status": "pending",
        "created_at": NOW,
        "updated_at": NOW,
        "retention_expires_at": NOW + timedelta(days=30),
    }
    fields.update(changes)
    return ComparisonSimulationRecord.model_validate(fields)


class FakeComparisonRunService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def create_or_resolve_report(self, record):
        self.calls.append(("create_or_resolve_report", record))
        self._raise()
        return ComparisonReportPersistenceResult(record=record, created=True)

    def create_or_resolve_simulation(self, record):
        self.calls.append(("create_or_resolve_simulation", record))
        self._raise()
        return ComparisonSimulationPersistenceResult(record=record, created=True)

    def get_report(self, evaluation_id):
        self.calls.append(("get_report", evaluation_id))
        self._raise()
        return _report(evaluation_id=evaluation_id)

    def get_simulation(self, simulation_execution_id):
        self.calls.append(("get_simulation", simulation_execution_id))
        self._raise()
        return _simulation(simulation_execution_id=simulation_execution_id)

    def list_simulations(self, evaluation_id):
        self.calls.append(("list_simulations", evaluation_id))
        self._raise()
        return (_simulation(evaluation_id=evaluation_id),)

    def replace_report_lifecycle(self, record):
        self.calls.append(("replace_report_lifecycle", record))
        self._raise()
        return record

    def replace_report_result_comparison(self, record):
        self.calls.append(("replace_report_result_comparison", record))
        self._raise()
        return record

    def replace_simulation_lifecycle(self, record):
        self.calls.append(("replace_simulation_lifecycle", record))
        self._raise()
        return record

    def attach_simulation_invocation(
        self,
        *,
        simulation_execution_id,
        expected_placeholder,
        modal_invocation_id,
        updated_at,
    ):
        self.calls.append(
            (
                "attach_simulation_invocation",
                {
                    "simulation_execution_id": simulation_execution_id,
                    "expected_placeholder": expected_placeholder,
                    "modal_invocation_id": modal_invocation_id,
                    "updated_at": updated_at,
                },
            )
        )
        self._raise()
        return _simulation(
            simulation_execution_id=simulation_execution_id,
            status="running",
            modal_invocation_id=modal_invocation_id,
            started_at=NOW,
            updated_at=updated_at,
        )


def _client(
    service: FakeComparisonRunService,
    *,
    authenticate=lambda: None,
) -> tuple[TestClient, dict[str, int]]:
    flask_calls = {"count": 0}
    flask_app = Flask(__name__)

    @flask_app.route("/<path:resource>", methods=["GET", "POST", "PUT"])
    def fallback(resource: str):
        flask_calls["count"] += 1
        return jsonify({"source": "flask", "resource": resource})

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=lambda: {},
        v2_comparison_run_service_factory=lambda: service,
        stage12_persistence_authenticator=authenticate,
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


def test_internal_routes_delegate_every_runtime_operation_to_canonical_service():
    service = FakeComparisonRunService()
    client, flask_calls = _client(service)
    report_json = _report().model_dump(mode="json")
    simulation_json = _simulation().model_dump(mode="json")
    prefix = "/internal/stage12/comparison-runs"

    responses = [
        client.post(f"{prefix}/reports/resolve", json=report_json),
        client.get(f"{prefix}/reports/{EVALUATION_ID}"),
        client.get(f"{prefix}/reports/{EVALUATION_ID}/simulations"),
        client.put(f"{prefix}/reports/{EVALUATION_ID}/lifecycle", json=report_json),
        client.put(f"{prefix}/reports/{EVALUATION_ID}/comparison", json=report_json),
        client.post(f"{prefix}/simulations/resolve", json=simulation_json),
        client.get(f"{prefix}/simulations/{SIMULATION_ID}"),
        client.put(
            f"{prefix}/simulations/{SIMULATION_ID}/lifecycle",
            json=simulation_json,
        ),
        client.post(
            f"{prefix}/simulations/{SIMULATION_ID}/invocation",
            json={
                "expected_placeholder": "dispatch-pending-1",
                "modal_invocation_id": "fc-123",
                "updated_at": NOW.isoformat(),
            },
        ),
    ]

    assert [response.status_code for response in responses] == [200] * len(responses)
    assert responses[0].json()["created"] is True
    assert responses[2].json()["items"][0]["simulation_execution_id"] == str(
        SIMULATION_ID
    )
    assert [name for name, _payload in service.calls] == [
        "create_or_resolve_report",
        "get_report",
        "list_simulations",
        "replace_report_lifecycle",
        "replace_report_result_comparison",
        "create_or_resolve_simulation",
        "get_simulation",
        "replace_simulation_lifecycle",
        "attach_simulation_invocation",
    ]
    assert flask_calls["count"] == 0


def test_internal_routes_reject_path_body_identifier_mismatches():
    service = FakeComparisonRunService()
    client, _flask_calls = _client(service)
    other_id = UUID("00000000-0000-4000-8000-000000000099")

    report = client.put(
        f"/internal/stage12/comparison-runs/reports/{other_id}/lifecycle",
        json=_report().model_dump(mode="json"),
    )
    simulation = client.put(
        f"/internal/stage12/comparison-runs/simulations/{other_id}/lifecycle",
        json=_simulation().model_dump(mode="json"),
    )

    assert report.status_code == 400
    assert simulation.status_code == 400
    assert service.calls == []


def test_internal_routes_return_secret_safe_errors_and_are_hidden_from_openapi():
    service = FakeComparisonRunService()
    client, _flask_calls = _client(service)
    service.error = ComparisonRunNotFoundError("internal detail")

    missing = client.get(f"/internal/stage12/comparison-runs/reports/{EVALUATION_ID}")
    schema = client.get("/v2/openapi.json")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "comparison record was not found"}
    assert not any(
        path.startswith("/internal/stage12") for path in schema.json()["paths"]
    )


def test_internal_routes_require_authentication_before_service_access():
    service = FakeComparisonRunService()
    client, _flask_calls = _client(service, authenticate=None)

    response = client.get(f"/internal/stage12/comparison-runs/reports/{EVALUATION_ID}")

    assert response.status_code == 403
    assert service.calls == []


def test_authenticator_accepts_only_the_environment_specific_service_accounts(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "staging")
    verify = Mock(
        return_value={
            "email": (
                "stage12-modal-staging@policyengine-simulation-entry."
                "iam.gserviceaccount.com"
            ),
            "email_verified": True,
        }
    )
    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", verify)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="signed-token",
    )

    auth.Stage12PersistenceAuthenticator()(credentials)

    assert verify.call_args.kwargs["audience"] == auth.STAGE12_PERSISTENCE_AUDIENCE


def test_authenticator_rejects_a_valid_google_token_from_another_identity(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setattr(
        auth.id_token,
        "verify_oauth2_token",
        lambda *_args, **_kwargs: {
            "email": "unrelated@policyengine-simulation-entry.iam.gserviceaccount.com",
            "email_verified": True,
        },
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="signed-token",
    )

    try:
        auth.Stage12PersistenceAuthenticator()(credentials)
    except HTTPException as error:
        assert error.status_code == 403
    else:  # pragma: no cover - documents the required rejection
        raise AssertionError("unapproved service account was accepted")
