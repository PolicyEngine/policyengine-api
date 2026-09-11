import json
from pathlib import Path

import pytest


def _load_payload(filename: str) -> str:
    return (Path(__file__).resolve().parents[1] / "data" / filename).read_text(
        encoding="utf-8"
    )


def _load_json_payload(filename: str) -> dict:
    return json.loads(_load_payload(filename))


def test_live_calculate_us_1(api_client):
    response = api_client.post(
        "/us/calculate",
        headers={"Content-Type": "application/json"},
        content=_load_payload("calculate_us_1_data.json"),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload is not None


def test_live_calculate_us_2(api_client):
    response = api_client.post(
        "/us/calculate",
        headers={"Content-Type": "application/json"},
        content=_load_payload("calculate_us_2_data.json"),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload is not None


def test_live_calculate_drops_deprecated_medical_input(
    api_client,
    integration_probe_id,
):
    deprecated_input_value = int(integration_probe_id.rsplit("-", 1)[-1], 16)

    response = api_client.post(
        "/us/calculate",
        json={
            "household": {
                "people": {
                    "you": {
                        "age": {"2026": 40},
                        "medical_out_of_pocket_expenses": {
                            "2026": deprecated_input_value
                        },
                    }
                }
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok", payload
    assert "medical_out_of_pocket_expenses" not in payload["result"]["people"]["you"]
    assert any(
        "medical_out_of_pocket_expenses" in warning and "deprecated" in warning.lower()
        for warning in payload["warnings"]
    )


def test_live_calculate_us_federal_and_california_credits(
    api_client,
    integration_probe_id,
):
    request_payload = _load_json_payload("live_us_credits_household.json")
    request_payload["integration_probe_id"] = f"{integration_probe_id}-us-credits"

    response = api_client.post("/us/calculate", json=request_payload)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok", payload
    tax_unit = payload["result"]["tax_units"]["tax unit"]
    assert tax_unit["eitc"]["2025"] == pytest.approx(4328.0, abs=0.01)
    assert tax_unit["ctc"]["2025"] == pytest.approx(2200.0, abs=0.01)
    assert tax_unit["ca_eitc"]["2025"] == pytest.approx(395.86, abs=0.01)


def test_live_calculate_uk_universal_credit_in_scotland(
    api_client,
    integration_probe_id,
):
    request_payload = _load_json_payload("live_uk_universal_credit_household.json")
    request_payload["integration_probe_id"] = f"{integration_probe_id}-uk-uc"

    response = api_client.post("/uk/calculate", json=request_payload)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok", payload
    benefit_unit = payload["result"]["benunits"]["benefit unit"]
    assert benefit_unit["universal_credit"]["2025"] == pytest.approx(
        6229.80,
        abs=0.01,
    )
