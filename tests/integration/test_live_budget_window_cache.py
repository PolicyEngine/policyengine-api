import json
from pathlib import Path


def _load_reform_payload(filename: str) -> dict:
    return json.loads(
        (Path(__file__).resolve().parents[1] / "data" / filename).read_text(
            encoding="utf-8"
        )
    )


def _get_current_law_id(api_client) -> int:
    metadata_response = api_client.get("/us/metadata")
    metadata_response.raise_for_status()
    return metadata_response.json()["result"]["current_law_id"]


def _create_utah_reform_policy(api_client) -> int:
    policy_response = api_client.post(
        "/us/policy",
        json=_load_reform_payload("utah_reform.json"),
    )
    assert policy_response.status_code in (200, 201)
    return policy_response.json()["result"]["policy_id"]


def test_live_budget_window_completed_result_cache(
    api_client,
    integration_probe_id,
    poll_live_endpoint,
):
    current_law_id = _get_current_law_id(api_client)
    policy_id = _create_utah_reform_policy(api_client)

    path = f"/us/economy/{policy_id}/over/{current_law_id}/budget-window"
    params = {
        "region": "ut",
        "start_year": "2026",
        "window_size": 1,
        "staging_probe": f"{integration_probe_id}-budget-window-cache",
    }

    first_payload = poll_live_endpoint(
        api_client,
        path,
        params,
        route_name="budget-window",
    )

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


def test_live_budget_window_multi_year_run(
    api_client,
    integration_probe_id,
    poll_live_endpoint,
):
    current_law_id = _get_current_law_id(api_client)
    policy_id = _create_utah_reform_policy(api_client)

    path = f"/us/economy/{policy_id}/over/{current_law_id}/budget-window"
    params = {
        "region": "ut",
        "start_year": "2026",
        "window_size": 2,
        "staging_probe": f"{integration_probe_id}-budget-window-multi-year",
    }

    payload = poll_live_endpoint(
        api_client,
        path,
        params,
        route_name="budget-window",
    )

    assert payload["status"] == "ok", payload
    assert payload["progress"] == 100, payload
    result = payload["result"]
    assert result is not None, payload
    assert result["kind"] == "budgetWindow", payload
    assert result["windowSize"] == 2, payload
    assert result["startYear"] == "2026", payload
    assert result["endYear"] == "2027", payload
    assert [impact["year"] for impact in result["annualImpacts"]] == [
        "2026",
        "2027",
    ]
    assert result["totals"]["year"] == "Total", payload


def test_live_budget_window_failed_batch_mapping(
    api_client,
    integration_probe_id,
    poll_live_endpoint,
):
    current_law_id = _get_current_law_id(api_client)
    policy_id = _create_utah_reform_policy(api_client)

    path = f"/us/economy/{policy_id}/over/{current_law_id}/budget-window"
    params = {
        "region": "ut",
        "dataset": "hf://policyengine/nonexistent-budget-window-test.h5@0.0.0",
        "start_year": "2026",
        "window_size": 1,
        "staging_probe": f"{integration_probe_id}-budget-window-failure",
    }

    payload = poll_live_endpoint(
        api_client,
        path,
        params,
        route_name="budget-window",
    )

    assert payload["status"] == "error", payload
    assert payload["result"] is None, payload
    assert payload["error"], payload
    assert isinstance(payload["completed_years"], list), payload
    assert isinstance(payload["computing_years"], list), payload
    assert isinstance(payload["queued_years"], list), payload
