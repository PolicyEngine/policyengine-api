import json
from pathlib import Path


EXCLUDED_YEARLY_VARIABLES = {"members"}


def _load_household_payload() -> dict:
    return json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "us_household.json").read_text(
            encoding="utf-8"
        )
    )


def _collect_yearly_metadata_variables(metadata: dict) -> set[str]:
    return {
        variable_name
        for variable_name, variable in metadata["variables"].items()
        if variable["definitionPeriod"] == "year"
        and variable_name not in EXCLUDED_YEARLY_VARIABLES
    }


def _collect_yearly_result_variables(result: dict, metadata: dict) -> set[str]:
    variables = set()

    for entity_group in result.values():
        for entity in entity_group.values():
            for variable_name in entity:
                if variable_name in EXCLUDED_YEARLY_VARIABLES:
                    continue
                if variable_name not in metadata["variables"]:
                    continue
                if metadata["variables"][variable_name]["definitionPeriod"] != "year":
                    continue
                variables.add(variable_name)

    return variables


def test_live_calculate_full_yearly_variable_contract(api_client):
    metadata_response = api_client.get("/us/metadata")
    metadata_response.raise_for_status()
    metadata = metadata_response.json()["result"]

    calculate_response = api_client.post(
        "/us/calculate-full",
        headers={"Content-Type": "application/json"},
        json={"household": _load_household_payload(), "policy": {}},
    )

    assert calculate_response.status_code == 200, calculate_response.text
    result = calculate_response.json()["result"]

    metadata_var_set = _collect_yearly_metadata_variables(metadata)
    result_var_set = _collect_yearly_result_variables(result, metadata)

    assert result_var_set == metadata_var_set, {
        "result_only": sorted(result_var_set.difference(metadata_var_set)),
        "metadata_only": sorted(metadata_var_set.difference(result_var_set)),
    }
