"""The Flask catch-all error handler records unhandled exceptions in telemetry."""

from flask import Flask

from policyengine_api.observability import runtime
from policyengine_api.routes import error_routes

ENGINE_FAILURE = "engine exploded"
EXISTING_500_BODY = {"status": "error", "message": ENGINE_FAILURE, "result": None}


def _make_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
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
        raising=False,
    )

    response = _make_client().get("/explode")

    assert response.status_code == 500
    assert response.get_json() == EXISTING_500_BODY
    assert len(recorded_calls) == 1
    recorded_error, recorded_options = recorded_calls[0]
    assert isinstance(recorded_error, RuntimeError)
    assert str(recorded_error) == ENGINE_FAILURE
    assert recorded_options == {"status_code": 500}


def test_not_found_is_not_recorded_as_unhandled_exception(monkeypatch):
    recorded_calls = []
    monkeypatch.setattr(
        error_routes,
        "record_unhandled_exception",
        lambda error, **options: recorded_calls.append((error, options)),
        raising=False,
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
