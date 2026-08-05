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

    simulation_gateway_response = api_client.get("/simulation-gateway-check")
    assert simulation_gateway_response.status_code == 200, (
        simulation_gateway_response.text
    )
    assert simulation_gateway_response.json() == {
        "status": "healthy",
        "simulation_gateway": "healthy",
    }


def test_cloud_run_candidate_metadata_and_policy(
    api_client,
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


def test_cloud_run_candidate_stage6_read_route_contracts(api_client):
    specification_response = api_client.get("/specification")
    assert specification_response.status_code == 200, specification_response.text
    specification = specification_response.json()
    assert specification["openapi"] == "3.0.0"
    assert specification["info"]["title"] == "PolicyEngine API"
    assert specification["info"]["version"]

    uk_metadata_response = api_client.get(
        "/uk/metadata",
        headers={"X-PolicyEngine-Request-Id": "stage6-uk-metadata"},
    )
    assert uk_metadata_response.status_code == 200, uk_metadata_response.text
    uk_metadata = uk_metadata_response.json()
    assert uk_metadata["status"] == "ok"
    assert uk_metadata["message"] is None
    assert uk_metadata["result"]["current_law_id"] == 1
    assert (
        uk_metadata_response.headers["X-PolicyEngine-Request-Id"]
        == "stage6-uk-metadata"
    )

    invalid_country_response = api_client.get("/zz/metadata")
    assert invalid_country_response.status_code == 400
    assert invalid_country_response.json() == {
        "status": "error",
        "message": (
            "Country zz not found. Available countries are: uk, us, ca, ng, il"
        ),
    }
