"""Flask fallback metadata route: large bodies stream, small bodies keep Content-Length."""

import importlib
import json
import sys
from types import SimpleNamespace

import pytest
from flask import Flask

from policyengine_api.utils.streaming_json import STREAMING_THRESHOLD_BYTES

SERVICE_MODULE = "policyengine_api.services.metadata_service"
ROUTE_MODULE = "policyengine_api.routes.metadata_routes"


class _MetadataService:
    metadata_by_country: dict = {}

    def get_metadata(self, country_id: str):
        return self.metadata_by_country[country_id]


def _load_metadata_blueprint_with_fake_service():
    """Import the real route module against a fake service module.

    The real ``MetadataService`` imports every country package at module
    import, so the route module is loaded with the fake installed first and
    the module cache is restored afterwards.
    """

    sentinel = object()
    original_route_module = sys.modules.get(ROUTE_MODULE, sentinel)
    original_service_module = sys.modules.get(SERVICE_MODULE, sentinel)
    sys.modules.pop(ROUTE_MODULE, None)
    sys.modules[SERVICE_MODULE] = SimpleNamespace(MetadataService=_MetadataService)
    try:
        return importlib.import_module(ROUTE_MODULE).metadata_bp
    finally:
        if original_route_module is sentinel:
            sys.modules.pop(ROUTE_MODULE, None)
        else:
            sys.modules[ROUTE_MODULE] = original_route_module
        if original_service_module is sentinel:
            sys.modules.pop(SERVICE_MODULE, None)
        else:
            sys.modules[SERVICE_MODULE] = original_service_module


@pytest.fixture
def flask_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(_load_metadata_blueprint_with_fake_service())
    return app.test_client()


def test_flask_metadata_streams_bodies_above_cloud_run_response_cap(flask_client):
    large_value = "x" * (STREAMING_THRESHOLD_BYTES + 1024)
    _MetadataService.metadata_by_country = {"us": {"large_value": large_value}}

    response = flask_client.get("/us/metadata")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.headers.get("Content-Length") is None
    assert json.loads(response.get_data()) == {
        "status": "ok",
        "message": None,
        "result": {"large_value": large_value},
    }


def test_flask_metadata_below_streaming_threshold_keeps_content_length(flask_client):
    _MetadataService.metadata_by_country = {"uk": {"small_value": "x" * 2_000}}

    response = flask_client.get("/uk/metadata")

    assert response.status_code == 200
    assert int(response.headers["Content-Length"]) == len(response.get_data())
    assert json.loads(response.get_data())["result"] == {"small_value": "x" * 2_000}
