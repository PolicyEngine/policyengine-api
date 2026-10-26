"""Read-only checks for deployed Cloud Run v2 metadata preview routes."""

import os
import time
import tomllib
from pathlib import Path

import httpx
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
    expected_paths.update(
        {
            "/v2/parameters/children",
            "/v2/economy-options",
            "/v2/model-catalog",
            "/v2/model-catalog/variables",
            "/v2/model-catalog/parameters",
        }
    )
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

    assert response.status_code == 422, response.text[:500]
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["message"]
    assert "result" not in payload or payload["result"] is None


def _timed_get(
    api_client: httpx.Client, path: str, **request_options: object
) -> tuple[httpx.Response, float]:
    started = time.perf_counter()
    response = api_client.get(path, **request_options)
    return response, time.perf_counter() - started


def _record_route_times(
    country_id: str, route_times: list[tuple[str, float, httpx.Response]]
) -> None:
    """Append each route's time and size to the GitHub job summary, when there is one.

    The release workflow runs this test against each Cloud Run candidate, so
    the summary keeps every release's staging and production route times.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        f"\n#### v2 catalog route times ({country_id})\n",
        "| Request | Time (ms) | Body (bytes, uncompressed) |",
        "| --- | ---: | ---: |",
    ]
    lines.extend(
        f"| {label} | {seconds * 1000:.0f} | {len(response.content)} |"
        for label, seconds, response in route_times
    )
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n")


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_live_v2_catalog_parts_load_on_demand(api_client, country_id: str) -> None:
    expected_version = _installed_policyengine_version()
    route_times: list[tuple[str, float, httpx.Response]] = []

    catalog_response, seconds = _timed_get(
        api_client, "/v2/model-catalog", params={"country_id": country_id}
    )
    route_times.append(
        ("/v2/model-catalog (running version)", seconds, catalog_response)
    )
    catalog = _assert_ok(catalog_response, expected_version)
    assert catalog["regions"]
    assert catalog["economy_options"]["region"]
    assert "variables" not in catalog
    pinned = {"country_id": country_id, "policyengine_version": expected_version}

    variables_response, seconds = _timed_get(
        api_client, "/v2/model-catalog/variables", params=pinned
    )
    route_times.append(("/v2/model-catalog/variables", seconds, variables_response))
    repeated_variables, seconds = _timed_get(
        api_client, "/v2/model-catalog/variables", params=pinned
    )
    route_times.append(
        ("/v2/model-catalog/variables (repeated)", seconds, repeated_variables)
    )
    variables = _assert_ok(variables_response, expected_version)
    assert variables["variables"]
    assert variables_response.headers["cache-control"] == "public, max-age=86400"
    assert repeated_variables.headers["etag"] == variables_response.headers["etag"]
    revalidated, seconds = _timed_get(
        api_client,
        "/v2/model-catalog/variables",
        params=pinned,
        headers={"If-None-Match": variables_response.headers["etag"]},
    )
    route_times.append(
        ("/v2/model-catalog/variables (revalidated)", seconds, revalidated)
    )
    assert revalidated.status_code == 304

    parameter_name = _assert_ok(
        api_client.get("/v2/parameters", params={**pinned, "limit": 1}),
        expected_version,
    )["items"][0]["name"]
    parameters_response, seconds = _timed_get(
        api_client,
        "/v2/model-catalog/parameters",
        params={**pinned, "name": parameter_name},
    )
    route_times.append(
        ("/v2/model-catalog/parameters (1 name)", seconds, parameters_response)
    )
    parameters = _assert_ok(parameters_response, expected_version)
    assert [parameter["name"] for parameter in parameters["parameters"]] == [
        parameter_name
    ]
    assert parameters["parameters"][0]["values"]
    assert parameters["missing_names"] == []

    _record_route_times(country_id, route_times)
