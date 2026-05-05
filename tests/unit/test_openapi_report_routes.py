from pathlib import Path

import yaml


def _load_spec() -> dict:
    spec_path = Path(__file__).parents[2] / "policyengine_api" / "openapi_spec.yaml"
    return yaml.safe_load(spec_path.read_text(encoding="utf-8"))


def _result_properties(response_schema: dict) -> dict:
    return response_schema["content"]["application/json"]["schema"]["properties"][
        "result"
    ]["properties"]


def test_report_output_openapi_responses_include_run_timestamp_fields():
    spec = _load_spec()
    paths = spec["paths"]
    timestamp_fields = {"requested_at", "started_at", "finished_at"}

    response_schemas = [
        paths["/{country_id}/report"]["post"]["responses"]["200"],
        paths["/{country_id}/report"]["post"]["responses"]["201"],
        paths["/{country_id}/report"]["patch"]["responses"]["200"],
        paths["/{country_id}/report/{report_id}"]["get"]["responses"]["200"],
    ]

    for response_schema in response_schemas:
        result_properties = _result_properties(response_schema)
        assert timestamp_fields.issubset(result_properties)
        for field in timestamp_fields:
            assert result_properties[field]["type"] == "string"
            assert result_properties[field]["nullable"] is True
