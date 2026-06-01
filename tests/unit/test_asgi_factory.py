import importlib
import json
import sys

from fastapi.testclient import TestClient
from flask import Flask, Response, jsonify, make_response, request
from flask_cors import CORS

from policyengine_api.asgi_factory import create_asgi_app


def create_test_wsgi_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    @app.get("/fallback")
    def fallback():
        response = make_response("flask fallback", 202)
        response.headers["X-Fallback"] = "preserved"
        response.set_cookie("fallback-cookie", "present")
        return response

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
    assert response.headers["vary"] == "Origin"


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
