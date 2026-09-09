"""Shared loader for the legacy public OpenAPI specification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import yaml
from policyengine_api.constants import VERSION
from policyengine_api.json_types import JSONObject
from policyengine_api.query_parameters import (
    AnnualEconomyQuery,
    BudgetWindowEconomyQuery,
)
from policyengine_api.spm import SPMProvenance, SPMSelection


DEFAULT_SPECIFICATION_PATH = Path(__file__).with_name("openapi_spec.yaml")


def _openapi_30_schema(value):
    """Convert Pydantic's optional JSON Schema fields to OpenAPI 3.0 nullable."""
    if isinstance(value, list):
        return [_openapi_30_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _openapi_30_schema(item) for key, item in value.items()}
    if "const" in result:
        result["enum"] = [result.pop("const")]
    variants = result.get("anyOf", [])
    if {"type": "null"} in variants:
        non_null = [item for item in variants if item != {"type": "null"}]
        if len(non_null) != 1:
            raise ValueError("SPM optional schemas must have one non-null type")
        result.pop("anyOf")
        result.update(non_null[0])
        result["nullable"] = True
    return result


def _economy_query_parameters(model):
    """Publish the same complete scalar query contract used by Flask."""
    schema = model.model_json_schema()
    result = []
    for name, field in model.model_fields.items():
        parameter = {"name": name, "in": "query", "required": field.is_required()}
        description = field.description
        if description:
            parameter["description"] = description
        if field.deprecated:
            parameter["deprecated"] = True
        if name == "spm":
            parameter["content"] = {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/SPMSelection"}
                }
            }
        else:
            parameter["schema"] = _openapi_30_schema(schema["properties"][name])
        result.append(parameter)
    return result


def load_specification(
    path: Path = DEFAULT_SPECIFICATION_PATH,
    version: str = VERSION,
) -> JSONObject:
    """Load the static specification and set the deployed package version."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("info"), dict):
        raise ValueError("OpenAPI specification must contain an info object")
    document["info"]["version"] = version
    schemas = document.get("components", {}).get("schemas", {})
    for name, model in {
        "SPMSelection": SPMSelection,
        "SPMProvenance": SPMProvenance,
    }.items():
        if name in schemas:
            schemas[name] = _openapi_30_schema(model.model_json_schema())
    economy_path = "/{country_id}/economy/{policy_id}/over/{baseline_policy_id}"
    for suffix, query_model in (
        ("", AnnualEconomyQuery),
        ("/budget-window", BudgetWindowEconomyQuery),
    ):
        operation = document.get("paths", {}).get(economy_path + suffix, {}).get("get")
        if operation is not None:
            operation["parameters"] = [
                parameter
                for parameter in operation.get("parameters", [])
                if parameter["in"] != "query"
            ] + _economy_query_parameters(query_model)
    # YAML accepts both quoted and numeric response codes. JSON object keys are
    # strings; normalize before Flask sorts them while serializing the document.
    return cast(JSONObject, json.loads(json.dumps(document)))


OPENAPI_SPECIFICATION = load_specification()
