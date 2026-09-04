"""Read-only checks for deployed Cloud Run v2 metadata preview routes."""

from pathlib import Path
import tomllib

import pytest


REPO = Path(__file__).parents[2]
PAGED_RESOURCES = (
    "tax-benefit-models",
    "tax-benefit-model-versions",
    "variables",
    "parameters",
    "parameter-values",
    "datasets",
    "regions",
)


def _installed_policyengine_version() -> str:
    dependencies = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["dependencies"]
    prefix = "policyengine[models]=="
    matches = [
        item.removeprefix(prefix) for item in dependencies if item.startswith(prefix)
    ]
    assert len(matches) == 1
    return matches[0]


def _assert_ok(response, expected_version: str) -> dict:
    assert response.status_code == 200, response.text[:500]
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["message"] is None
    assert payload["result"]["policyengine_version"] == expected_version
    return payload["result"]


def test_live_v2_openapi_describes_every_preview_resource(api_client) -> None:
    response = api_client.get("/v2/openapi.json")

    assert response.status_code == 200, response.text[:500]
    document = response.json()
    expected_paths = {f"/v2/{resource}" for resource in PAGED_RESOURCES}
    expected_paths.update({"/v2/parameters/children", "/v2/economy-options"})
    assert expected_paths <= document["paths"].keys()
    assert all("get" in document["paths"][path] for path in expected_paths)
    assert "V2ErrorResponse" in document["components"]["schemas"]


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_live_v2_resources_use_the_deployed_policyengine_version(
    api_client,
    country_id: str,
) -> None:
    expected_version = _installed_policyengine_version()
    query = {"country_id": country_id, "limit": 1}

    for resource in PAGED_RESOURCES:
        result = _assert_ok(
            api_client.get(f"/v2/{resource}", params=query),
            expected_version,
        )
        assert result["limit"] == 1
        assert result["items"]
        if resource == "parameters":
            assert "values" not in result["items"][0]

    economy_options = _assert_ok(
        api_client.get("/v2/economy-options", params={"country_id": country_id}),
        expected_version,
    )
    assert economy_options["region"]
    assert economy_options["datasets"]

    explicit = _assert_ok(
        api_client.get(
            "/v2/variables",
            params={
                "country_id": country_id,
                "policyengine_version": expected_version,
                "limit": 1,
            },
        ),
        expected_version,
    )
    repeated = _assert_ok(
        api_client.get("/v2/variables", params=query),
        expected_version,
    )
    assert repeated == explicit


def test_live_v2_invalid_version_returns_a_typed_error(api_client) -> None:
    response = api_client.get(
        "/v2/variables",
        params={"country_id": "us", "policyengine_version": "not a version"},
    )

    assert response.status_code == 400, response.text[:500]
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["message"]
    assert "result" not in payload or payload["result"] is None
