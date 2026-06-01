import os


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
        create_household_response = api_client.post(
            "/us/household",
            json={
                "label": f"cloud-run-smoke-{integration_probe_id}",
                "data": {
                    "people": {
                        "you": {
                            "age": {"2026": 40},
                        }
                    }
                },
            },
        )
        assert create_household_response.status_code == 201, (
            create_household_response.text
        )
        household_id = str(create_household_response.json()["result"]["household_id"])

    household_response = api_client.get(f"/us/household/{household_id}")
    assert household_response.status_code == 200, household_response.text
    household_payload = household_response.json()
    assert household_payload["status"] == "ok"
    assert str(household_payload["result"]["id"]) == household_id
