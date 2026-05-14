from pathlib import Path


def _load_payload(filename: str) -> str:
    return (Path(__file__).resolve().parents[1] / "data" / filename).read_text(
        encoding="utf-8"
    )


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
