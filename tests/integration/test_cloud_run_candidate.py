def test_cloud_run_candidate_health_routes(api_client):
    health_response = api_client.get("/health")
    assert health_response.status_code == 200, health_response.text
    assert health_response.json() == {"status": "healthy"}

    for removed_probe_path in ("/liveness-check", "/readiness-check"):
        removed_probe_response = api_client.get(removed_probe_path)
        assert removed_probe_response.status_code == 404, removed_probe_path

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


def test_cloud_run_candidate_serves_no_legacy_documentation_routes(api_client):
    for path in ("/", "/specification", "/simulations"):
        response = api_client.get(path)
        assert response.status_code == 404, (path, response.text)


def test_cloud_run_candidate_stage6_read_route_contracts(api_client):
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


def test_cloud_run_candidate_user_routes_fail_closed_without_a_token(api_client):
    """User-owned routes must never become readable without a credential."""
    for path in ("/v2/me", "/v2/user-policies", "/v2/user-reports"):
        for headers in ({}, {"PolicyEngine-Unauthenticated-User": "not-a-uuid"}):
            response = api_client.get(
                path,
                params={
                    "country_id": "us",
                    "user_id": "00000000-0000-0000-0000-000000000000",
                },
                headers=headers,
            )
            assert response.status_code == 401, (path, response.text)
            assert response.headers["www-authenticate"].startswith("Bearer")
            assert response.json()["status"] == "error"
