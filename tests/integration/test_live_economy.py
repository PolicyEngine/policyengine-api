import json
import os
import time
from pathlib import Path


INTEGRATION_TIMEOUT_SECONDS = float(
    os.environ.get("STAGING_API_TEST_TIMEOUT_SECONDS", "900")
)
INTEGRATION_POLL_INTERVAL_SECONDS = float(
    os.environ.get("STAGING_API_TEST_POLL_INTERVAL_SECONDS", "5")
)


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
        period["name"] for period in metadata["economy_options"]["time_period"]
    ]
    return str(max(period_names))


def _poll_economy(api_client, path: str, params: dict) -> dict:
    deadline = time.monotonic() + INTEGRATION_TIMEOUT_SECONDS

    while True:
        response = api_client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()

        if payload["status"] != "computing":
            return payload

        assert time.monotonic() < deadline, (
            f"Timed out polling the economy route; last response was {payload}"
        )
        time.sleep(INTEGRATION_POLL_INTERVAL_SECONDS)


def test_live_economy_smoke(api_client, integration_probe_id):
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

    payload = _poll_economy(
        api_client,
        f"/us/economy/{policy_id}/over/{current_law_id}",
        {
            "region": region,
            "time_period": time_period,
            "staging_probe": f"{integration_probe_id}-smoke",
        },
    )

    assert payload["status"] == "ok", payload
    assert payload["result"] is not None, payload
    assert "budget" in payload["result"], payload


def test_live_utah_macro_reform(api_client, integration_probe_id):
    test_year = "2025"
    default_policy_id = 2

    policy_response = api_client.post(
        "/us/policy",
        json=_load_reform_payload("utah_reform.json"),
    )
    assert policy_response.status_code in (200, 201)
    policy_id = policy_response.json()["result"]["policy_id"]

    payload = _poll_economy(
        api_client,
        f"/us/economy/{policy_id}/over/{default_policy_id}",
        {
            "region": "ut",
            "time_period": test_year,
            "staging_probe": f"{integration_probe_id}-utah",
        },
    )

    assert payload["status"] == "ok", payload
    result = payload["result"]
    assert result is not None

    cost = round(result["budget"]["budgetary_impact"] / 1e6, 1)
    assert (cost / 1867.4 - 1) < 0.01, (
        f"Expected budgetary impact to be 1867.4 million, got {cost} million"
    )

    assert (result["intra_decile"]["all"]["Lose less than 5%"] / 0.534 - 1) < 0.01, (
        f"Expected 53.4% of people to lose less than 5%, got "
        f"{result['intra_decile']['all']['Lose less than 5%']}"
    )
