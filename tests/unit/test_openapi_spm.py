"""The served legacy specification describes the canonical SPM HTTP contract."""

import json

from flask import Flask

from policyengine_api.routes.system_routes import system_bp
from policyengine_api.spm import SPMProvenance, SPMSelection
from policyengine_api.query_parameters import (
    AnnualEconomyQuery,
    BudgetWindowEconomyQuery,
)
from policyengine_api.specification import load_specification


def test_economy_query_and_receipt_schemas_match_public_http_contract():
    spec = load_specification()
    paths = spec["paths"]
    base = "/{country_id}/economy/{policy_id}/over/{baseline_policy_id}"
    for suffix, query_model in (
        ("", AnnualEconomyQuery),
        ("/budget-window", BudgetWindowEconomyQuery),
    ):
        operation = paths[base + suffix]["get"]
        parameters = {
            item["name"]: item
            for item in operation["parameters"]
            if item["in"] == "query"
        }
        assert set(parameters) == set(query_model.model_fields)
        for name, field in query_model.model_fields.items():
            assert parameters[name]["required"] is field.is_required()
        assert parameters["spm"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/SPMSelection"
        }
        assert parameters["dataset"]["schema"]["default"] == "default"
        assert parameters["include_district_breakdowns"]["deprecated"] is True
        assert parameters["target"]["schema"]["enum"] == (
            ["general"] if suffix else ["general", "cliff"]
        )
        if suffix:
            assert parameters["window_size"]["schema"]["minimum"] == 1
            assert parameters["window_size"]["schema"]["maximum"] == 75
        result = operation["responses"]["200"]["content"]["application/json"]["schema"][
            "properties"
        ]["result"]
        if suffix:
            result = result["properties"]["annualImpacts"]["items"]
        assert result["properties"]["spm_config"] == {
            "$ref": "#/components/schemas/SPMSelection"
        }
        assert result["properties"]["spm_provenance"] == {
            "$ref": "#/components/schemas/SPMWorkerProvenance"
        }
        assert operation["responses"]["400"]["$ref"].endswith("SPMValidationError")
    receipt = spec["components"]["schemas"]["SPMWorkerProvenance"]
    assert receipt["required"] == ["baseline", "reform"]
    for side in receipt["required"]:
        assert receipt["properties"][side]["items"] == {
            "$ref": "#/components/schemas/SPMProvenance"
        }


def test_metadata_discovery_and_selection_constraints_are_published():
    spec = load_specification()
    metadata = spec["paths"]["/{country_id}/metadata"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["properties"]["result"]["properties"]
    assert metadata["spm"] == {"$ref": "#/components/schemas/SPMDiscovery"}
    discovery = spec["components"]["schemas"]["SPMDiscovery"]
    assert discovery["required"] == ["available"]
    assert set(discovery["properties"]) == {"available", "settings_schema", "defaults"}
    selection = spec["components"]["schemas"]["SPMSelection"]
    assert selection["properties"]["as_of"]["format"] == "date"
    assert "oneOf" in selection
    assert selection["oneOf"][1]["required"] == ["geography_kind", "geography_id"]


def test_household_specification_exposes_creation_without_content_update():
    paths = load_specification()["paths"]
    assert "put" not in paths["/{country_id}/household/{household_id}"]
    description = " ".join(
        paths["/{country_id}/household"]["post"]["description"].split()
    )
    assert "immutable" in description.lower()
    assert "new household" in description.lower()


def test_spm_documentation_uses_public_models_and_actual_route_envelopes():
    app = Flask(__name__)
    app.register_blueprint(system_bp)
    response = app.test_client().get("/specification")
    assert response.status_code == 200
    spec = response.get_json()
    assert spec["openapi"] == "3.0.0"
    paths = spec["paths"]
    schemas = spec["components"]["schemas"]
    selection_ref = {"$ref": "#/components/schemas/SPMSelection"}
    provenance_ref = {"$ref": "#/components/schemas/SPMProvenance"}

    for name, model in {
        "SPMSelection": SPMSelection,
        "SPMProvenance": SPMProvenance,
    }.items():
        schema = schemas[name]
        assert set(schema["properties"]) == set(model.model_fields)
        assert schema["additionalProperties"] is False
        assert '"type": "null"' not in json.dumps(schema)

    selection = schemas["SPMSelection"]["properties"]
    assert selection["geography_kind"]["enum"] == ["county", "national", "metro"]
    assert all("default" not in field for field in selection.values())
    for field in ("forecast_content_sha256", "scenario", "geography_id", "as_of"):
        assert selection[field]["type"] == "string"
        assert selection[field]["nullable"] is True
    assert schemas["SPMProvenance"]["properties"]["runtime_versions"][
        "additionalProperties"
    ] == {
        "type": "string",
        "nullable": True,
    }

    for route in ("calculate", "calculate-full"):
        operation = paths[f"/{{country_id}}/{route}"]["post"]
        request = operation["requestBody"]["content"]["application/json"]["schema"]
        assert set(request["properties"]) == {"household", "policy", "spm"}
        assert request["properties"]["spm"] == selection_ref
    assert (
        paths["/{country_id}/calculate-full"]["post"]["operationId"]
        == "get_calculate_full"
    )

    for path, method in (
        ("/{country_id}/calculate", "post"),
        ("/{country_id}/calculate-full", "post"),
        ("/{country_id}/household/{household_id}/policy/{policy_id}", "get"),
    ):
        operation = paths[path][method]
        result = operation["responses"]["200"]["content"]["application/json"]["schema"][
            "properties"
        ]
        assert {"status", "message", "result"} <= set(result)
        assert result["spm_config"] == selection_ref
        assert result["spm_provenance"] == provenance_ref
        assert (
            operation["responses"]["400"]["$ref"]
            == "#/components/responses/SPMValidationError"
        )

    for path, method in (("/{country_id}/household", "post"),):
        operation = paths[path][method]
        request = operation["requestBody"]["content"]["application/json"]["schema"]
        assert set(request["properties"]) == {"data", "label", "spm"}
        assert request["required"] == ["data"]
        assert request["properties"]["spm"] == selection_ref
        assert (
            operation["responses"]["400"]["$ref"]
            == "#/components/responses/SPMValidationError"
        )

    for method in ("get",):
        operation = paths["/{country_id}/household/{household_id}"][method]
        result = operation["responses"]["200"]["content"]["application/json"]["schema"][
            "properties"
        ]["result"]
        assert result["properties"]["spm"] == selection_ref
        assert result["properties"]["household_json"]["type"] == "object"

    error = spec["components"]["responses"]["SPMValidationError"]["content"][
        "application/json"
    ]["schema"]
    assert set(error["required"]) == {"status", "message"}
    assert {"result", "errors"} <= set(error["properties"])
    assert error["properties"]["errors"]["items"]["required"] == ["message"]
    assert "code" in error["properties"]["errors"]["items"]["properties"]
    assert error["properties"]["result"]["nullable"] is True
