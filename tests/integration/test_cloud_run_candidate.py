import os

import pytest


def test_cloud_run_candidate_health_routes(api_client):
    health_response = api_client.get("/health")
    assert health_response.status_code == 200, health_response.text
    assert health_response.json() == {"status": "healthy"}

    liveness_response = api_client.get("/liveness-check")
    assert liveness_response.status_code == 200, liveness_response.text
    assert liveness_response.text == "OK"

    readiness_response = api_client.get("/readiness-check")
    assert readiness_response.status_code == 200, readiness_response.text
    assert readiness_response.text == "OK"

    simulation_gateway_response = api_client.get("/health/simulation-gateway")
    assert simulation_gateway_response.status_code == 200, (
        simulation_gateway_response.text
    )
    assert simulation_gateway_response.json() == {
        "status": "healthy",
        "simulation_gateway": "healthy",
    }


def test_cloud_run_candidate_metadata_policy_and_household(
    api_client,
    integration_probe_id,
):
    metadata_response = api_client.get("/us/metadata")
    assert metadata_response.status_code == 200, metadata_response.text
    metadata = metadata_response.json()["result"]
    current_law_id = metadata["current_law_id"]

    policy_response = api_client.get(f"/us/policy/{current_law_id}")
    assert policy_response.status_code == 200, policy_response.text
    policy_payload = policy_response.json()
    assert policy_payload["status"] == "ok"
    assert policy_payload["result"]["id"] == current_law_id

    household_id = os.environ.get("CLOUD_RUN_SMOKE_HOUSEHOLD_ID") or None
    if household_id is None:
        pytest.fail(
            "CLOUD_RUN_SMOKE_HOUSEHOLD_ID must be set to a pre-existing "
            "non-production household fixture. Cloud Run smoke tests must not "
            "create households."
        )

    household_response = api_client.get(f"/us/household/{household_id}")
    assert household_response.status_code == 200, household_response.text
    household_payload = household_response.json()
    assert household_payload["status"] == "ok"
    assert str(household_payload["result"]["id"]) == household_id
