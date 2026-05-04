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


def _poll_budget_window(api_client, path: str, params: dict) -> dict:
    deadline = time.monotonic() + INTEGRATION_TIMEOUT_SECONDS

    while True:
        response = api_client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()

        if payload["status"] != "computing":
            return payload

        assert time.monotonic() < deadline, (
            f"Timed out polling the budget-window route; last response was {payload}"
        )
        time.sleep(INTEGRATION_POLL_INTERVAL_SECONDS)


def test_live_budget_window_completed_result_cache(api_client, integration_probe_id):
    metadata_response = api_client.get("/us/metadata")
    metadata_response.raise_for_status()
    current_law_id = metadata_response.json()["result"]["current_law_id"]

    policy_response = api_client.post(
        "/us/policy",
        json=_load_reform_payload("utah_reform.json"),
    )
    assert policy_response.status_code in (200, 201)
    policy_id = policy_response.json()["result"]["policy_id"]

    path = f"/us/economy/{policy_id}/over/{current_law_id}/budget-window"
    params = {
        "region": "ut",
        "start_year": "2025",
        "window_size": 1,
        "staging_probe": f"{integration_probe_id}-budget-window-cache",
    }

    first_payload = _poll_budget_window(api_client, path, params)

    assert first_payload["status"] == "ok", first_payload
    assert first_payload["progress"] == 100, first_payload
    assert first_payload["result"] is not None, first_payload
    assert first_payload["result"]["kind"] == "budgetWindow", first_payload
    assert first_payload["result"]["windowSize"] == 1, first_payload

    second_response = api_client.get(path, params=params)
    second_response.raise_for_status()
    second_payload = second_response.json()

    assert second_payload["status"] == "ok", second_payload
    assert second_payload["progress"] == 100, second_payload
    assert second_payload["result"] == first_payload["result"]
    assert second_response.headers["X-PolicyEngine-Budget-Window-Cache"] == "result-hit"
