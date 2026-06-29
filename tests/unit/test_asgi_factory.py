import importlib
import json
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from flask import Flask, Response, jsonify, make_response, request
from flask_cors import CORS
from policyengine_api.asgi_factory import _add_vary_origin, create_asgi_app
from starlette.responses import Response as ASGIResponse


def create_test_wsgi_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    @app.get("/fallback")
    def fallback():
        response = make_response("flask fallback", 202)
        response.headers["X-Fallback"] = "preserved"
        response.set_cookie("fallback-cookie", "present")
        return response

    @app.get("/large-fallback")
    def large_fallback():
        return Response("x" * 2_000, status=200, mimetype="text/plain")

    @app.get("/request-echo")
    def request_echo():
        response = jsonify(
            {
                "cookie": request.cookies.get("session_id"),
                "header": request.headers.get("X-Request-Trace"),
            }
        )
        response.headers["X-Echo"] = "present"
        return response

    @app.get("/readiness-check")
    def readiness_check():
        return Response("OK", status=200, mimetype="text/plain")

    @app.get("/liveness-check")
    def liveness_check():
        return Response("OK", status=200, mimetype="text/plain")

    @app.get("/specification")
    def specification():
        return jsonify({"openapi": "3.0.0", "info": {"title": "fallback"}})

    return app


def test_native_health_route_is_fastapi_json():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    ("existing_vary", "expected_vary"),
    [
        (None, "Origin"),
        ("Accept-Encoding", "Accept-Encoding, Origin"),
        ("Origin", "Origin"),
        ("Accept-Encoding, origin", "Accept-Encoding, origin"),
    ],
)
def test_add_vary_origin_preserves_existing_values(existing_vary, expected_vary):
    response = ASGIResponse()
    if existing_vary is not None:
        response.headers["Vary"] = existing_vary

    _add_vary_origin(response)

    assert response.headers["Vary"] == expected_vary


def test_asgi_entrypoint_imports_and_serves_health(monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "1")
    sys.modules.pop("policyengine_api.asgi", None)

    asgi_module = importlib.import_module("policyengine_api.asgi")
    response = TestClient(asgi_module.app).get("/health")

    assert asgi_module.application is asgi_module.app
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_fastapi_documentation_routes_fall_through_to_flask_404():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path)

        assert response.status_code == 404
        assert "text/html" in response.headers["content-type"]
        assert "swagger" not in response.text.lower()


def test_flask_fallback_preserves_status_body_headers_and_cookies():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    response = client.get("/fallback")

    assert response.status_code == 202
    assert response.content == b"flask fallback"
    assert response.headers["x-fallback"] == "preserved"
    assert response.headers["set-cookie"].startswith("fallback-cookie=present")
    assert response.headers["content-type"].startswith("text/html")


def test_large_flask_fallback_response_supports_http_gzip():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    response = client.get(
        "/large-fallback",
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert response.text == "x" * 2_000


def test_request_headers_and_cookies_pass_through_to_flask_fallback():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))
    client.cookies.set("session_id", "session-123")

    response = client.get(
        "/request-echo",
        headers={"X-Request-Trace": "trace-123"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "cookie": "session-123",
        "header": "trace-123",
    }
    assert response.headers["x-echo"] == "present"


def test_flask_cors_behavior_is_preserved_for_fallback_routes():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    response = client.get(
        "/fallback",
        headers={"Origin": "https://app.policyengine.org"},
    )

    assert response.status_code == 202
    assert (
        response.headers["access-control-allow-origin"]
        == "https://app.policyengine.org"
    )
    vary_values = {value.strip() for value in response.headers["vary"].split(",")}
    assert vary_values == {"Origin", "Accept-Encoding"}


def test_health_route_uses_same_reflected_cors_policy():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    response = client.get(
        "/health",
        headers={"Origin": "https://app.policyengine.org"},
    )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://app.policyengine.org"
    )
    assert response.headers["vary"] == "Origin"


def test_public_simulation_gateway_health_probe_checks_gateway():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    with patch(
        "policyengine_api.libs.simulation_api_modal.SimulationAPIModal"
    ) as simulation_api:
        simulation_api.return_value.health_check.return_value = True

        response = client.get("/simulation-gateway-check")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "simulation_gateway": "healthy",
    }
    simulation_api.assert_called_once_with()
    simulation_api.return_value.health_check.assert_called_once_with()


def test_public_simulation_gateway_health_probe_reports_failure():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    with patch(
        "policyengine_api.libs.simulation_api_modal.SimulationAPIModal"
    ) as simulation_api:
        simulation_api.return_value.health_check.return_value = False

        response = client.get("/simulation-gateway-check")

    assert response.status_code == 503


def test_existing_health_and_specification_paths_fall_back_to_flask():
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    readiness = client.get("/readiness-check")
    liveness = client.get("/liveness-check")
    specification = client.get("/specification")

    assert readiness.status_code == 200
    assert readiness.content == b"OK"
    assert readiness.headers["content-type"].startswith("text/plain")
    assert liveness.status_code == 200
    assert liveness.content == b"OK"
    assert liveness.headers["content-type"].startswith("text/plain")
    assert specification.status_code == 200
    assert json.loads(specification.content) == {
        "openapi": "3.0.0",
        "info": {"title": "fallback"},
    }
