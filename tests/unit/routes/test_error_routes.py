"""The Flask catch-all error handler records unhandled exceptions in telemetry."""

import importlib
from dataclasses import replace

import pytest
from flask import Flask
from policyengine_observability import (
    CustomLogDestination,
    LoggingConfig,
    OTelConfig,
    configure,
    instrument_flask,
)

from policyengine_api.observability import runtime
from policyengine_api.routes import error_routes

# policyengine_api.observability re-exports the runtime object under the name of
# its submodule, so the submodule whose global record_unhandled_exception reads
# is imported by its full name.
runtime_module = importlib.import_module("policyengine_api.observability.runtime")

ENGINE_FAILURE = "engine exploded"
EXISTING_500_BODY = {"status": "error", "message": ENGINE_FAILURE, "result": None}


class _CollectedRecords:
    """Keeps every structured record a runtime delivers, in delivery order."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def write(self, record: dict[str, object]) -> None:
        self.records.append(record)

    def with_event_name(self, event_name: str) -> list[dict[str, object]]:
        return [
            record for record in self.records if record.get("event.name") == event_name
        ]


@pytest.fixture
def collected_records():
    return _CollectedRecords()


@pytest.fixture
def collecting_runtime(monkeypatch, collected_records):
    """Point record_unhandled_exception at a real runtime that keeps its records."""
    observability_runtime = configure(
        replace(
            runtime.config,
            logging=LoggingConfig(
                destinations=(
                    CustomLogDestination(
                        name="collected-records",
                        writer_factory=lambda: collected_records,
                        delivery="inline",
                    ),
                ),
            ),
            otel=OTelConfig(enabled=False),
        )
    )
    monkeypatch.setattr(runtime_module, "runtime", observability_runtime)
    yield observability_runtime
    observability_runtime.shutdown()


def _make_client(observability_runtime=None):
    app = Flask(__name__)
    app.config["TESTING"] = True
    if observability_runtime is not None:
        # Same order as the API app: instrument Flask, then register handlers.
        instrument_flask(app, observability_runtime)
    app.register_blueprint(error_routes.error_bp)

    @app.route("/explode")
    def explode():
        raise RuntimeError(ENGINE_FAILURE)

    return app.test_client()


def test_unhandled_exception_is_recorded_and_still_returns_500(monkeypatch):
    recorded_calls = []
    monkeypatch.setattr(
        error_routes,
        "record_unhandled_exception",
        lambda error, **options: recorded_calls.append((error, options)),
    )

    response = _make_client().get("/explode")

    assert response.status_code == 500
    assert response.get_json() == EXISTING_500_BODY
    assert len(recorded_calls) == 1
    recorded_error, recorded_options = recorded_calls[0]
    assert isinstance(recorded_error, RuntimeError)
    assert str(recorded_error) == ENGINE_FAILURE
    assert recorded_options == {"status_code": 500}


def test_unhandled_exception_adds_one_exception_record_to_its_request(
    collecting_runtime, collected_records
):
    response = _make_client(collecting_runtime).get("/explode")

    assert response.status_code == 500
    assert response.get_json() == EXISTING_500_BODY
    exception_records = collected_records.with_event_name("exception.recorded")
    completed_records = collected_records.with_event_name("request.completed")
    assert len(exception_records) == 1
    assert len(completed_records) == 1
    exception_record = exception_records[0]
    assert exception_record["error.type"] == "RuntimeError"
    assert exception_record["error.message"] == ENGINE_FAILURE
    assert "raise RuntimeError(ENGINE_FAILURE)" in exception_record["error.stack"]
    assert exception_record["error.handled"] is False
    assert exception_record["http.response.status_code"] == 500
    assert exception_record["http.route"] == "/explode"
    assert exception_record["request.id"] == completed_records[0]["request.id"]


def test_unhandled_exception_is_on_its_request_completion_record(
    collecting_runtime, collected_records
):
    _make_client(collecting_runtime).get("/explode")

    completed_record = collected_records.with_event_name("request.completed")[0]
    assert completed_record["outcome"] == "error"
    assert completed_record["http.response.status_code"] == 500
    assert completed_record.get("error.type") == "RuntimeError"
    assert completed_record.get("error.message") == ENGINE_FAILURE
    assert "raise RuntimeError(ENGINE_FAILURE)" in completed_record.get(
        "error.stack", ""
    )


def test_not_found_is_not_recorded_as_unhandled_exception(monkeypatch):
    recorded_calls = []
    monkeypatch.setattr(
        error_routes,
        "record_unhandled_exception",
        lambda error, **options: recorded_calls.append((error, options)),
    )

    response = _make_client().get("/missing")

    assert response.status_code == 404
    assert recorded_calls == []


def test_recording_failure_leaves_500_response_unchanged(monkeypatch):
    attempted_errors = []

    def fail_to_record(error, **_options):
        attempted_errors.append(error)
        message = "observability unavailable"
        raise RuntimeError(message)

    monkeypatch.setattr(runtime, "record_exception", fail_to_record)

    response = _make_client().get("/explode")

    assert len(attempted_errors) == 1
    assert response.status_code == 500
    assert response.get_json() == EXISTING_500_BODY
