"""Served simulation schemas agree with real Flask persistence envelopes."""

from copy import deepcopy
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask
import jsonschema
import pytest

from policyengine_api.data.v1_models import Simulation
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.specification import build_specification_router
from policyengine_api.routes import simulation_routes
from policyengine_api.routes.error_routes import error_bp
from policyengine_api.routes.system_routes import system_bp
from policyengine_api.services.simulation_service import SimulationService


@pytest.fixture
def simulation_http(orm_session_factory, monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(error_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(simulation_routes.simulation_bp)
    monkeypatch.setattr(
        simulation_routes,
        "simulation_service",
        SimulationService(orm_session_factory),
    )
    return app.test_client()


def _json_schema(value):
    """Translate OpenAPI 3.0 nullable for the installed JSON Schema validator."""
    if isinstance(value, list):
        return [_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {name: _json_schema(item) for name, item in value.items()}
    if result.pop("nullable", False):
        return {"anyOf": [result, {"type": "null"}]}
    return result


def _validate(spec, schema, payload):
    document = _json_schema({**deepcopy(schema), "components": spec["components"]})
    jsonschema.Draft7Validator(document).validate(payload)


def _response_schema(spec, path, method, status):
    return spec["paths"][path][method]["responses"][str(status)]["content"][
        "application/json"
    ]["schema"]


def test_actual_flask_and_native_specification_publish_simulation_operations(
    simulation_http,
):
    flask_response = simulation_http.get("/specification")
    app = FastAPI()
    app.include_router(build_specification_router(NativeRouteDependencies.defaults()))
    native_response = TestClient(app).get("/specification")
    assert flask_response.status_code == native_response.status_code == 200
    spec = flask_response.get_json()
    assert spec == native_response.json()
    collection = spec["paths"]["/{country_id}/simulation"]
    detail = spec["paths"]["/{country_id}/simulation/{simulation_id}"]
    assert set(collection) == {"post", "patch"}
    assert set(detail) == {"get"}
    assert collection["post"]["operationId"] == "create_simulation"
    assert collection["patch"]["operationId"] == "update_simulation"
    assert detail["get"]["operationId"] == "get_simulation"
    for method in ("post", "patch"):
        assert "linked household" in collection[method]["description"]
        assert "SPM_SETTINGS_UNSUPPORTED" in collection[method]["description"]
        assert collection[method]["requestBody"]["required"] is True
    simulation_id = next(
        item for item in detail["get"]["parameters"] if item["name"] == "simulation_id"
    )
    assert simulation_id["in"] == "path"
    assert simulation_id["required"] is True
    assert simulation_id["schema"] == {"type": "integer", "minimum": 1}


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize("selection", [None, {}, {"geography_kind": "national"}])
def test_simulation_schema_and_http_reject_independent_spm_selection(
    simulation_http, method, selection
):
    spec = simulation_http.get("/specification").get_json()
    path = "/{country_id}/simulation"
    operation = spec["paths"][path][method]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    payload = (
        {"population_id": "1", "population_type": "household", "policy_id": 1}
        if method == "post"
        else {"id": 1, "status": "complete", "output": {}}
    )
    _validate(spec, request_schema, payload)
    payload["spm"] = selection
    with pytest.raises(jsonschema.ValidationError):
        _validate(spec, request_schema, payload)
    response = simulation_http.open(
        "/us/simulation", method=method.upper(), json=payload
    )
    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "SPM_SETTINGS_UNSUPPORTED"
    _validate(spec, _response_schema(spec, path, method, 400), response.get_json())


@pytest.mark.parametrize("encode_output", [False, True], ids=["object", "json-string"])
def test_simulation_persistence_responses_preserve_spm_output_and_run_fields(
    simulation_http,
    encode_output,
):
    spec = simulation_http.get("/specification").get_json()
    path = "/{country_id}/simulation"
    create_payload = {
        "population_id": "1",
        "population_type": "household",
        "policy_id": 1,
    }
    created = simulation_http.post("/us/simulation", json=create_payload)
    assert created.status_code == 201
    pending = created.get_json()["result"]
    assert pending["status"] == "pending"
    assert pending["output"] is None
    assert pending["error_message"] is None
    assert pending["latest_successful_run_id"] is None
    assert pending["active_run_id"] is not None
    assert pending["simulation_spec_schema_version"] == 1
    assert isinstance(pending["simulation_spec_json"], str)
    assert set(pending) == {column.name for column in Simulation.__table__.columns}
    record_schema = spec["components"]["schemas"]["SimulationRecord"]
    assert set(record_schema["properties"]) == set(pending)
    assert set(record_schema["required"]) == set(pending)
    _validate(spec, _response_schema(spec, path, "post", 201), created.get_json())
    repeated = simulation_http.post("/us/simulation", json=create_payload)
    assert repeated.status_code == 200
    assert repeated.get_json()["result"] == pending
    _validate(spec, _response_schema(spec, path, "post", 200), repeated.get_json())

    output = {
        "status": "ok",
        "message": None,
        "result": {"people": {}},
        "spm_config": {"geography_kind": "national"},
        "spm_provenance": {
            "forecast_id": "test-forecast",
            "forecast_sha256": "a" * 64,
            "scenario": "baseline",
            "geography_kind": "national",
            "runtime_versions": {"policyengine-us": "test"},
            "years": {},
            "geographies": [],
            "composition_method": "test",
            "storage_method": "test",
        },
    }
    update_payload = {
        "id": pending["id"],
        "status": "complete",
        "output": json.dumps(output) if encode_output else output,
    }
    _validate(spec, {"$ref": "#/components/schemas/SimulationUpdate"}, update_payload)
    updated = simulation_http.patch("/us/simulation", json=update_payload)
    assert updated.status_code == 200
    complete = updated.get_json()["result"]
    assert complete["active_run_id"] is None
    assert complete["latest_successful_run_id"] == pending["active_run_id"]
    assert isinstance(complete["output"], str)
    assert json.loads(complete["output"]) == output
    _validate(spec, _response_schema(spec, path, "patch", 200), updated.get_json())
    _validate(
        spec, {"$ref": "#/components/schemas/StoredHouseholdOutputEnvelope"}, output
    )
    fetched = simulation_http.get(f"/us/simulation/{pending['id']}")
    assert fetched.status_code == 200
    assert fetched.get_json()["message"] is None
    assert fetched.get_json()["result"] == complete
    _validate(
        spec,
        _response_schema(spec, path + "/{simulation_id}", "get", 200),
        fetched.get_json(),
    )


def test_simulation_schema_covers_existing_null_metadata_and_error_state(
    simulation_http, orm_session_factory
):
    with orm_session_factory.begin() as session:
        historical = Simulation(
            country_id="us",
            api_version="test",
            population_id="1",
            population_type="household",
            policy_id=1,
            status="error",
            error_message="Calculation failed",
        )
        session.add(historical)
        session.flush()
        simulation_id = historical.id
    response = simulation_http.get(f"/us/simulation/{simulation_id}")
    assert response.status_code == 200
    result = response.get_json()["result"]
    for field in (
        "output",
        "simulation_spec_json",
        "simulation_spec_schema_version",
        "active_run_id",
        "latest_successful_run_id",
    ):
        assert result[field] is None
    spec = simulation_http.get("/specification").get_json()
    _validate(
        spec,
        _response_schema(spec, "/{country_id}/simulation/{simulation_id}", "get", 200),
        response.get_json(),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"id": 1},
        {"id": 1, "api_version": "ignored"},
        {"id": 1, "status": None, "output": None, "error_message": None},
        {"id": 1, "status": "complete"},
        {"id": 1, "status": "complete", "output": None},
        {"id": 1, "status": "running"},
    ],
)
def test_update_schema_matches_http_required_fields_and_status_checks(
    simulation_http, payload
):
    spec = simulation_http.get("/specification").get_json()
    with pytest.raises(jsonschema.ValidationError):
        _validate(spec, {"$ref": "#/components/schemas/SimulationUpdate"}, payload)
    response = simulation_http.patch("/us/simulation", json=payload)
    assert response.status_code == 400
    _validate(
        spec,
        _response_schema(spec, "/{country_id}/simulation", "patch", 400),
        response.get_json(),
    )


@pytest.mark.parametrize("method", ["get", "patch"])
def test_documented_simulation_not_found_envelope_matches_http(simulation_http, method):
    response = (
        simulation_http.get("/us/simulation/999")
        if method == "get"
        else simulation_http.patch(
            "/us/simulation", json={"id": 999, "status": "error"}
        )
    )
    assert response.status_code == 404
    spec = simulation_http.get("/specification").get_json()
    path = "/{country_id}/simulation" + ("/{simulation_id}" if method == "get" else "")
    _validate(spec, _response_schema(spec, path, method, 404), response.get_json())


@pytest.mark.parametrize("ignored_version", [None, 42, {"ignored": True}])
def test_update_schema_accepts_any_ignored_api_version_value(
    simulation_http, ignored_version
):
    created = simulation_http.post(
        "/us/simulation",
        json={"population_id": "1", "population_type": "household", "policy_id": 1},
    )
    assert created.status_code == 201
    record = created.get_json()["result"]
    payload = {"id": record["id"], "status": "pending", "api_version": ignored_version}
    response = simulation_http.patch("/us/simulation", json=payload)
    assert response.status_code == 200
    assert response.get_json()["result"]["api_version"] == record["api_version"]
    spec = simulation_http.get("/specification").get_json()
    _validate(spec, {"$ref": "#/components/schemas/SimulationUpdate"}, payload)


def test_stored_scalar_string_output_is_returned_unchanged(simulation_http):
    created = simulation_http.post(
        "/us/simulation",
        json={"population_id": "1", "population_type": "household", "policy_id": 1},
    )
    assert created.status_code == 201
    simulation_id = created.get_json()["result"]["id"]
    response = simulation_http.patch(
        "/us/simulation",
        json={"id": simulation_id, "status": "complete", "output": json.dumps("hello")},
    )
    assert response.status_code == 200
    assert response.get_json()["result"]["output"] == "hello"
    fetched = simulation_http.get(f"/us/simulation/{simulation_id}")
    assert fetched.status_code == 200
    assert fetched.get_json()["result"]["output"] == "hello"
    spec = simulation_http.get("/specification").get_json()
    _validate(
        spec,
        _response_schema(spec, "/{country_id}/simulation/{simulation_id}", "get", 200),
        fetched.get_json(),
    )
    description = spec["components"]["schemas"]["SimulationRecord"]["properties"][
        "output"
    ]["description"]
    assert "scalar strings" in description
    assert "unchanged" in description
