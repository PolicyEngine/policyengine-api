import importlib
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from flask import Flask, Response
from policyengine_api.asgi_factory import (
    NativeRouteDependencies,
    create_asgi_app,
)
from policyengine_api.constants import COUNTRIES
from policyengine_api.migration_flags import (
    BACKEND_RESPONSE_HEADER,
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.request_context import REQUEST_ID_HEADER
from policyengine_api.utils.payload_validators import validate_country


class _HealthySimulationGateway:
    def health_check(self) -> bool:
        return True


class _MetadataReader:
    def __init__(self, metadata_by_country, *, error: Exception | None = None):
        self.metadata_by_country = metadata_by_country
        self.error = error
        self.calls: list[str] = []

    def get_metadata(self, country_id: str):
        self.calls.append(country_id)
        if self.error is not None:
            raise self.error
        return self.metadata_by_country[country_id]


def _settings(metadata: RouteImplementation) -> RouteImplementationSettings:
    return RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=metadata,
    )


def _dependencies(reader: _MetadataReader) -> NativeRouteDependencies:
    return NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=_HealthySimulationGateway,
        metadata_reader_factory=lambda: reader,
        specification_provider=lambda: {},
    )


def _metadata_wsgi_app(reader: _MetadataReader) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = False

    @app.after_request
    def mark_flask_response(response):
        response.headers["X-Served-By"] = "flask"
        return response

    @app.route("/<country_id>/metadata", methods=["GET"])
    @validate_country
    def metadata(country_id: str):
        payload = {
            "status": "ok",
            "message": None,
            "result": reader.get_metadata(country_id),
        }
        return Response(
            json.dumps(payload),
            status=200,
            mimetype="application/json",
        )

    return app


def _native_client(native_reader, fallback_reader=None) -> TestClient:
    fallback_reader = fallback_reader or _MetadataReader(
        {country_id: {"source": "flask"} for country_id in COUNTRIES}
    )
    return TestClient(
        create_asgi_app(
            _metadata_wsgi_app(fallback_reader),
            route_settings=_settings(RouteImplementation.FASTAPI_NATIVE),
            dependencies=_dependencies(native_reader),
        ),
        raise_server_exceptions=False,
    )


@pytest.mark.parametrize("country_id", COUNTRIES)
def test_native_metadata_supports_every_existing_country(country_id):
    reader = _MetadataReader(
        {country: {"country": country, "source": "native"} for country in COUNTRIES}
    )

    response = _native_client(reader).get(f"/{country_id}/metadata")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {"country": country_id, "source": "native"},
    }
    assert "X-Served-By" not in response.headers
    assert reader.calls == [country_id]


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_native_metadata_matches_flask_response_contract(country_id):
    metadata = {
        "current_law_id": 2 if country_id == "us" else 1,
        "economy_options": {
            "region": [{"name": country_id}],
            "time_period": [{"name": 2026, "label": "2026"}],
        },
    }
    fallback_reader = _MetadataReader({country_id: metadata})
    native_reader = _MetadataReader({country_id: metadata})
    wsgi_app = _metadata_wsgi_app(fallback_reader)
    fallback_client = TestClient(
        create_asgi_app(
            wsgi_app,
            route_settings=_settings(RouteImplementation.FLASK_FALLBACK),
            dependencies=_dependencies(native_reader),
        )
    )
    native_client = TestClient(
        create_asgi_app(
            wsgi_app,
            route_settings=_settings(RouteImplementation.FASTAPI_NATIVE),
            dependencies=_dependencies(native_reader),
        )
    )

    fallback_response = fallback_client.get(f"/{country_id}/metadata")
    native_response = native_client.get(f"/{country_id}/metadata")

    assert native_response.status_code == fallback_response.status_code == 200
    assert native_response.content == fallback_response.content
    assert (
        native_response.headers["content-type"]
        == fallback_response.headers["content-type"]
    )
    assert native_response.json() == fallback_response.json()


def test_native_invalid_country_matches_legacy_flask_error():
    reader = _MetadataReader({})
    wsgi_app = _metadata_wsgi_app(reader)
    fallback_client = TestClient(
        create_asgi_app(
            wsgi_app,
            route_settings=_settings(RouteImplementation.FLASK_FALLBACK),
            dependencies=_dependencies(reader),
        )
    )
    native_client = TestClient(
        create_asgi_app(
            wsgi_app,
            route_settings=_settings(RouteImplementation.FASTAPI_NATIVE),
            dependencies=_dependencies(reader),
        )
    )

    fallback_response = fallback_client.get("/zz/metadata")
    native_response = native_client.get("/zz/metadata")

    assert native_response.status_code == fallback_response.status_code == 400
    assert native_response.content == fallback_response.content
    assert (
        native_response.headers["content-type"]
        == fallback_response.headers["content-type"]
    )
    assert native_response.json() == {
        "status": "error",
        "message": "Country zz not found. Available countries are: uk, us, ca, ng, il",
    }
    assert reader.calls == []


def test_country_validation_is_shared_by_flask_and_fastapi():
    validation = importlib.import_module("policyengine_api.country_validation")

    assert validation.ensure_supported_country("us") == "us"
    with pytest.raises(validation.InvalidCountryError) as raised:
        validation.ensure_supported_country("zz")

    assert raised.value.country_id == "zz"
    assert raised.value.available_country_ids == COUNTRIES
    assert str(raised.value) == (
        "Country zz not found. Available countries are: uk, us, ca, ng, il"
    )


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "POST"])
def test_non_get_metadata_methods_continue_to_flask(method):
    native_reader = _MetadataReader({"us": {"source": "native"}})
    fallback_reader = _MetadataReader({"us": {"source": "flask"}})
    client = _native_client(native_reader, fallback_reader)

    response = client.request(method, "/us/metadata")

    assert response.headers["X-Served-By"] == "flask"
    assert native_reader.calls == []


def test_native_metadata_preserves_query_strings_and_shared_middleware():
    reader = _MetadataReader({"us": {"source": "native"}})
    client = _native_client(reader)

    response = client.get(
        "/us/metadata?client=app-v2",
        headers={
            REQUEST_ID_HEADER: "metadata-request",
            "Origin": "https://app.policyengine.org",
        },
    )

    assert response.status_code == 200
    assert reader.calls == ["us"]
    assert response.headers[REQUEST_ID_HEADER] == "metadata-request"
    assert response.headers["access-control-allow-origin"] == (
        "https://app.policyengine.org"
    )


def test_large_native_metadata_response_supports_http_gzip():
    reader = _MetadataReader({"us": {"large_value": "x" * 2_000}})

    response = _native_client(reader).get(
        "/us/metadata",
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert response.json()["result"]["large_value"] == "x" * 2_000


def test_native_metadata_does_not_mutate_cached_metadata():
    metadata = {"nested": {"values": [1, 2, 3]}}
    original = deepcopy(metadata)
    reader = _MetadataReader({"us": metadata})

    response = _native_client(reader).get("/us/metadata")

    assert response.status_code == 200
    assert metadata == original
    assert response.json()["result"] == original


def test_native_metadata_failure_is_500_without_exception_details():
    reader = _MetadataReader({}, error=RuntimeError("private failure detail"))

    response = _native_client(reader).get(
        "/us/metadata",
        headers={
            REQUEST_ID_HEADER: "failed-metadata-request",
            "Origin": "https://app.policyengine.org",
        },
    )

    assert response.status_code == 500
    assert "private failure detail" not in response.text
    assert response.headers[REQUEST_ID_HEADER] == "failed-metadata-request"
    assert response.headers[BACKEND_RESPONSE_HEADER]
    assert response.headers["access-control-allow-origin"] == (
        "https://app.policyengine.org"
    )
