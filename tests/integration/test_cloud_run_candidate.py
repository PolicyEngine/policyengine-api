from datetime import date
import math


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


def test_cloud_run_candidate_current_law_economy(api_client, poll_live_endpoint):
    """Exercise the candidate's selected worker without creating a reform policy."""
    response = api_client.get("/us/metadata")
    response.raise_for_status()
    metadata = response.json()["result"]
    current_law = metadata["current_law_id"]
    years = [
        int(period["name"])
        for period in metadata["economy_options"]["time_period"]
        if str(period["name"]).isdigit()
    ]
    assert years, "Metadata exposes no economy years"
    current_year = date.today().year
    year = str(
        max((value for value in years if value <= current_year), default=min(years))
    )
    payload = poll_live_endpoint(
        api_client,
        f"/us/economy/{current_law}/over/{current_law}",
        {"region": "ut", "time_period": year},
        route_name="Cloud Run candidate current-law economy",
    )
    assert payload["status"] == "ok", payload
    result = payload["result"]
    impact = result["budget"]["budgetary_impact"]
    assert isinstance(impact, int | float) and math.isfinite(impact), result
    assert impact == 0, "Comparing current law with itself must have zero budget impact"
    spm = metadata.get("spm", {})
    if spm.get("available"):
        defaults = spm["defaults"]
        config = result["spm_config"]
        assert isinstance(config, dict) and set(config) <= set(defaults)
        # HTTP transports may omit optional null settings; they may never
        # inherit a missing non-null default or introduce an unknown setting.
        assert all(config.get(key) == value for key, value in defaults.items())
        for side in ("baseline", "reform"):
            receipts = result["spm_provenance"][side]
            assert receipts, f"Missing {side} SPM receipts"
            for receipt in receipts:
                assert receipt["forecast_sha256"] == defaults["forecast_content_sha256"]
                assert receipt["scenario"] == defaults["scenario"]
                assert receipt["geography_kind"] == defaults["geography_kind"]
                assert year in receipt["years"]
