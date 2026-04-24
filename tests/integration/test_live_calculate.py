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
