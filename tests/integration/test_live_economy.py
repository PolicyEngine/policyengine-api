import json
import math
from pathlib import Path


def _load_reform_payload(filename: str) -> dict:
    return json.loads(
        (Path(__file__).resolve().parents[1] / "data" / filename).read_text(
            encoding="utf-8"
        )
    )


def _pick_region(metadata: dict) -> str:
    for region in metadata["economy_options"]["region"]:
        if region["name"] == "us":
            return "us"
    return metadata["economy_options"]["region"][0]["name"]


def _pick_time_period(metadata: dict) -> str:
    period_names = [
        str(period["name"]) for period in metadata["economy_options"]["time_period"]
    ]
    if "2025" in period_names:
        return "2025"
    return str(max(period_names))


def test_live_economy_smoke(api_client, integration_probe_id, poll_live_endpoint):
    liveness_response = api_client.get("/liveness-check")
    assert liveness_response.status_code == 200

    readiness_response = api_client.get("/readiness-check")
    assert readiness_response.status_code == 200

    metadata_response = api_client.get("/us/metadata")
    metadata_response.raise_for_status()
    metadata = metadata_response.json()["result"]

    current_law_id = metadata["current_law_id"]
    region = _pick_region(metadata)
    time_period = _pick_time_period(metadata)

    policy_response = api_client.post(
        "/us/policy",
        json=_load_reform_payload("utah_reform.json"),
    )
    assert policy_response.status_code in (200, 201)
    policy_id = policy_response.json()["result"]["policy_id"]

    payload = poll_live_endpoint(
        api_client,
        f"/us/economy/{policy_id}/over/{current_law_id}",
        {
            "region": region,
            "time_period": time_period,
            "staging_probe": f"{integration_probe_id}-smoke",
        },
        route_name="economy",
    )

    assert payload["status"] == "ok", payload
    assert payload["result"] is not None, payload
    assert "budget" in payload["result"], payload


def test_live_utah_macro_reform(api_client, integration_probe_id, poll_live_endpoint):
    test_year = "2025"
    default_policy_id = 2

    policy_response = api_client.post(
        "/us/policy",
        json=_load_reform_payload("utah_reform.json"),
    )
    assert policy_response.status_code in (200, 201)
    policy_id = policy_response.json()["result"]["policy_id"]

    payload = poll_live_endpoint(
        api_client,
        f"/us/economy/{policy_id}/over/{default_policy_id}",
        {
            "region": "ut",
            "time_period": test_year,
            "staging_probe": f"{integration_probe_id}-utah",
        },
        route_name="economy",
    )

    assert payload["status"] == "ok", payload
    result = payload["result"]
    assert result is not None

    budgetary_impact = result["budget"]["budgetary_impact"]
    assert isinstance(budgetary_impact, int | float), result
    assert math.isfinite(budgetary_impact), result

    lose_less_than_5 = result["intra_decile"]["all"]["Lose less than 5%"]
    assert isinstance(lose_less_than_5, int | float), result
    assert math.isfinite(lose_less_than_5), result
    assert 0 <= lose_less_than_5 <= 1, result
