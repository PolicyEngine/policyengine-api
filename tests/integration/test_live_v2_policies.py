"""Live staging checks for native v2 policies and user-owned resources.

The staging deployment runs this module against the tagged Cloud Run
candidate. Signed-in routes use a dedicated staging Auth0 test user whose
access token is obtained through the staging-only CI application's password
grant. Signed-out checks send a fresh random UUID per run in the
``PolicyEngine-Unauthenticated-User`` header and need no credential. Every
credential comes from the GitHub ``staging`` environment:

- ``STAGING_AUTH0_TEST_DOMAIN``: Auth0 domain issuing tokens whose ``iss``
  matches the staging ``PUBLIC_API_AUTH_ISSUER`` (variable);
- ``STAGING_AUTH0_TEST_AUDIENCE``: the Public API resource server identifier,
  equal to ``PUBLIC_API_AUTH_AUDIENCE`` (variable);
- ``STAGING_AUTH0_TEST_CLIENT_ID`` / ``STAGING_AUTH0_TEST_CLIENT_SECRET``: the
  CI application with the password grant enabled (secrets);
- ``STAGING_AUTH0_TEST_USERNAME`` / ``STAGING_AUTH0_TEST_PASSWORD``: the test
  user (secrets);
- ``STAGING_AUTH0_TEST_REALM`` (optional variable): a database connection name
  for the password-realm grant when the tenant has no default directory.

Missing settings fail the run instead of skipping it: the signed-in routes are
a staging deployment gate. The module never prints a token or credential. It
starts and ends by deleting the test user's PolicyEngine account, so staging
must not configure the Auth0 Management API deletion for this user's tenant
(``AUTH0_MANAGEMENT_*``), or the CI user would be removed from Auth0.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest


AUTH0_ENVIRONMENT = (
    "STAGING_AUTH0_TEST_DOMAIN",
    "STAGING_AUTH0_TEST_AUDIENCE",
    "STAGING_AUTH0_TEST_CLIENT_ID",
    "STAGING_AUTH0_TEST_CLIENT_SECRET",
    "STAGING_AUTH0_TEST_USERNAME",
    "STAGING_AUTH0_TEST_PASSWORD",
)
UNKNOWN_LEGACY_ID = 9_007_199_254_740_000
COUNTRY_ID = "us"
UNAUTHENTICATED_USER_HEADER = "PolicyEngine-Unauthenticated-User"


def _staging_user_token() -> str:
    values = {name: os.environ.get(name, "").strip() for name in AUTH0_ENVIRONMENT}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "The live signed-in route checks require staging Auth0 test "
            f"settings: {', '.join(missing)}"
        )
    domain = values["STAGING_AUTH0_TEST_DOMAIN"].removeprefix("https://").rstrip("/")
    form = {
        "grant_type": "password",
        "username": values["STAGING_AUTH0_TEST_USERNAME"],
        "password": values["STAGING_AUTH0_TEST_PASSWORD"],
        "audience": values["STAGING_AUTH0_TEST_AUDIENCE"],
        "client_id": values["STAGING_AUTH0_TEST_CLIENT_ID"],
        "client_secret": values["STAGING_AUTH0_TEST_CLIENT_SECRET"],
        "scope": "openid",
    }
    realm = os.environ.get("STAGING_AUTH0_TEST_REALM", "").strip()
    if realm:
        form["grant_type"] = "http://auth0.com/oauth/grant-type/password-realm"
        form["realm"] = realm
    response = httpx.post(f"https://{domain}/oauth/token", data=form, timeout=30.0)
    if response.status_code != 200:
        raise RuntimeError(
            f"Staging Auth0 password grant failed: HTTP {response.status_code}"
        )
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Staging Auth0 password grant returned no access token")
    return token


@pytest.fixture
def user_headers(api_base_url: str) -> dict[str, str]:
    # Depending on api_base_url skips local runs before any token request.
    del api_base_url
    return {"Authorization": f"Bearer {_staging_user_token()}"}


def _one_catalog_item(api_client, resource: str) -> dict:
    response = api_client.get(
        f"/v2/{resource}",
        params={"country_id": COUNTRY_ID, "limit": 1},
    )
    assert response.status_code == 200, response.text[:500]
    items = response.json()["result"]["items"]
    assert len(items) == 1
    return items[0]


def _v1_id(api_client, path: str, body: dict, field: str) -> int:
    response = api_client.post(f"/{COUNTRY_ID}/{path}", json=body)
    assert response.status_code in {200, 201}, response.text[:500]
    value = response.json()["result"][field]
    assert isinstance(value, int)
    return value


def _create_v1_artifacts(api_client) -> dict[str, int]:
    """Create (or reuse deduplicated) v1 artifacts without running compute."""

    policy_id = _v1_id(api_client, "policy", {"data": {}}, "policy_id")
    household_id = _v1_id(
        api_client,
        "household",
        {"label": "Stage 12A live probe", "data": {}},
        "household_id",
    )
    simulation_id = _v1_id(
        api_client,
        "simulation",
        {
            "population_id": COUNTRY_ID,
            "population_type": "geography",
            "policy_id": policy_id,
        },
        "id",
    )
    report_id = _v1_id(
        api_client,
        "report",
        {"simulation_1_id": simulation_id, "simulation_2_id": None, "year": "2026"},
        "id",
    )
    return {
        "policy": policy_id,
        "household": household_id,
        "simulation": simulation_id,
        "report": report_id,
    }


def _delete_account(api_client, headers: dict[str, str]) -> None:
    response = api_client.delete(
        "/v2/me", params={"country_id": COUNTRY_ID}, headers=headers
    )
    assert response.status_code == 204, response.text[:500]


def _browser_headers() -> dict[str, str]:
    """A fresh signed-out browser; its UUID never leaves the request headers."""

    return {UNAUTHENTICATED_USER_HEADER: str(uuid4())}


def _save_policy(api_client, headers: dict[str, str], legacy_policy_id: int) -> dict:
    response = api_client.post(
        "/v2/user-policies",
        params={"country_id": COUNTRY_ID},
        headers=headers,
        json={
            "country_id": COUNTRY_ID,
            "legacy_policy_id": legacy_policy_id,
            "name": "Stage 12A signed-out reform",
        },
    )
    assert response.status_code == 201, response.text[:500]
    return response.json()["result"]["item"]


def _policy_ids(api_client, headers: dict[str, str]) -> set[str]:
    response = api_client.get(
        "/v2/user-policies",
        params={"country_id": COUNTRY_ID, "limit": 1000},
        headers=headers,
    )
    assert response.status_code == 200, response.text[:500]
    return {item["id"] for item in response.json()["result"]["items"]}


def test_live_user_routes_reject_unauthenticated_requests(api_client) -> None:
    for method, path in (
        ("GET", "/v2/me"),
        ("GET", "/v2/me/export"),
        ("POST", "/v2/me/upgrade"),
        ("GET", "/v2/user-policies"),
        ("GET", "/v2/user-households"),
        ("GET", "/v2/user-simulations"),
        ("GET", "/v2/user-reports"),
    ):
        for headers in ({}, {UNAUTHENTICATED_USER_HEADER: "not-a-uuid"}):
            response = api_client.request(
                method,
                path,
                params={"country_id": COUNTRY_ID, "user_id": str(uuid4())},
                headers=headers,
                json={} if method == "POST" else None,
            )
            assert response.status_code == 401, (path, response.text[:500])
            assert response.headers["www-authenticate"].startswith("Bearer")
            assert response.json()["status"] == "error"


def test_live_native_policy_resources_and_v2_policy_save(
    api_client,
    integration_probe_id: str,
    user_headers: dict[str, str],
) -> None:
    model = _one_catalog_item(api_client, "tax-benefit-models")
    parameter = _one_catalog_item(api_client, "parameters")
    policy_body = {
        "country_id": COUNTRY_ID,
        "tax_benefit_model_id": model["id"],
        "parameter_values": [
            {
                "parameter_id": parameter["id"],
                "value": f"stage12a-native-{integration_probe_id}",
                "start_date": "2026-01-01T00:00:00Z",
            }
        ],
    }
    created = api_client.post(
        "/v2/policies", params={"country_id": COUNTRY_ID}, json=policy_body
    )
    assert created.status_code == 201, created.text[:500]
    created_item = created.json()["result"]["item"]
    policy_id = created_item["id"]
    assert created_item["parameter_values"][0]["parameter_name"] == parameter["name"]

    repeated = api_client.post(
        "/v2/policies", params={"country_id": COUNTRY_ID}, json=policy_body
    )
    assert repeated.status_code == 200, repeated.text[:500]
    assert repeated.json()["result"]["item"]["id"] == policy_id
    detail = api_client.get(
        f"/v2/policies/{policy_id}", params={"country_id": COUNTRY_ID}
    )
    assert detail.status_code == 200, detail.text[:500]
    assert detail.json()["result"]["item"] == created_item
    collection = api_client.get(
        "/v2/policies",
        params={
            "country_id": COUNTRY_ID,
            "tax_benefit_model_id": model["id"],
            "limit": 1,
        },
    )
    assert collection.status_code == 200, collection.text[:500]
    assert set(collection.json()["result"]) == {"items", "offset", "limit", "has_more"}

    saved = api_client.post(
        "/v2/user-policies",
        params={"country_id": COUNTRY_ID},
        headers=user_headers,
        json={"country_id": COUNTRY_ID, "policy_id": policy_id, "name": "v2 save"},
    )
    assert saved.status_code == 201, saved.text[:500]
    saved_item = saved.json()["result"]["item"]
    assert saved_item["policy_id"] == policy_id
    assert saved_item["legacy_policy_id"] is None
    deleted = api_client.delete(
        f"/v2/user-policies/{saved_item['id']}",
        params={"country_id": COUNTRY_ID},
        headers=user_headers,
    )
    assert deleted.status_code == 204, deleted.text[:500]


def test_live_signed_in_user_lifecycle(
    api_client,
    integration_probe_id: str,
    user_headers: dict[str, str],
) -> None:
    params = {"country_id": COUNTRY_ID}
    # Start from a clean account in case an earlier run stopped midway.
    _delete_account(api_client, user_headers)
    try:
        me = api_client.get("/v2/me", params=params, headers=user_headers)
        assert me.status_code == 200, me.text[:500]
        me_item = me.json()["result"]["item"]
        user_id = me_item["id"]
        assert me_item["primary_country"] == COUNTRY_ID

        patched_me = api_client.patch(
            "/v2/me",
            params=params,
            headers=user_headers,
            json={"first_name": "Stage 12A", "last_name": None},
        )
        assert patched_me.status_code == 200, patched_me.text[:500]
        assert patched_me.json()["result"]["item"]["first_name"] == "Stage 12A"

        legacy = _create_v1_artifacts(api_client)
        resources = {
            "user-policies": ("legacy_policy_id", legacy["policy"]),
            "user-households": ("legacy_household_id", legacy["household"]),
            "user-simulations": ("legacy_simulation_id", legacy["simulation"]),
            "user-reports": ("legacy_report_id", legacy["report"]),
        }
        for resource, (legacy_field, legacy_id) in resources.items():
            created = api_client.post(
                f"/v2/{resource}",
                params=params,
                headers=user_headers,
                json={
                    "country_id": COUNTRY_ID,
                    legacy_field: legacy_id,
                    "name": f"Stage 12A {resource} {integration_probe_id}",
                },
            )
            assert created.status_code == 201, (resource, created.text[:500])
            item = created.json()["result"]["item"]
            assert item["user_id"] == user_id
            assert item[legacy_field] == legacy_id

            missing = api_client.post(
                f"/v2/{resource}",
                params=params,
                headers=user_headers,
                json={"country_id": COUNTRY_ID, legacy_field: UNKNOWN_LEGACY_ID},
            )
            assert missing.status_code == 422, (resource, missing.text[:500])

            detail_path = f"/v2/{resource}/{item['id']}"
            detail = api_client.get(detail_path, params=params, headers=user_headers)
            assert detail.status_code == 200, (resource, detail.text[:500])
            assert detail.json()["result"]["item"] == item
            listed = api_client.get(
                f"/v2/{resource}",
                params={**params, legacy_field: legacy_id},
                headers=user_headers,
            )
            assert listed.status_code == 200, (resource, listed.text[:500])
            assert item["id"] in {row["id"] for row in listed.json()["result"]["items"]}
            patched = api_client.patch(
                detail_path,
                params=params,
                headers=user_headers,
                json={"description": "Renamed by the live probe"},
            )
            assert patched.status_code == 200, (resource, patched.text[:500])
            assert patched.json()["result"]["item"]["description"] == (
                "Renamed by the live probe"
            )
            deleted = api_client.delete(
                detail_path, params=params, headers=user_headers
            )
            assert deleted.status_code == 204, (resource, deleted.text[:500])
            absent = api_client.get(detail_path, params=params, headers=user_headers)
            assert absent.status_code == 404, (resource, absent.text[:500])

        policy = api_client.post(
            "/v2/user-policies",
            params=params,
            headers=user_headers,
            json={
                "country_id": COUNTRY_ID,
                "legacy_policy_id": legacy["policy"],
                "baseline": "current-law",
                "provenance": {"source": "manual"},
            },
        )
        assert policy.status_code == 201, policy.text[:500]
        policy_id = policy.json()["result"]["item"]["id"]
        report = api_client.post(
            "/v2/user-reports",
            params=params,
            headers=user_headers,
            json={
                "country_id": COUNTRY_ID,
                "legacy_report_id": legacy["report"],
                "user_policy_id": policy_id,
            },
        )
        assert report.status_code == 201, report.text[:500]
        report_id = report.json()["result"]["item"]["id"]

        exported = api_client.get("/v2/me/export", params=params, headers=user_headers)
        assert exported.status_code == 200, exported.text[:500]
        export = exported.json()["result"]
        assert export["user"]["id"] == user_id
        assert export["user"]["user_type"] == "standard"
        exported_report = next(
            row for row in export["reports"] if row["id"] == report_id
        )
        assert exported_report["user_policy_id"] == policy_id
        assert [row["id"] for row in export["policies"]] == [policy_id]

        _delete_account(api_client, user_headers)
        reprovisioned = api_client.get("/v2/me", params=params, headers=user_headers)
        assert reprovisioned.status_code == 200, reprovisioned.text[:500]
        assert reprovisioned.json()["result"]["item"]["id"] != user_id
        empty_export = api_client.get(
            "/v2/me/export", params=params, headers=user_headers
        )
        assert empty_export.status_code == 200, empty_export.text[:500]
        assert empty_export.json()["result"]["policies"] == []
    finally:
        _delete_account(api_client, user_headers)


def test_live_unauthenticated_users_round_trip_and_upgrade(
    api_client,
    user_headers: dict[str, str],
) -> None:
    """Exercise signed-out saving, conversion, and merge at sign-in.

    Every run uses fresh browser UUIDs and starts and ends by deleting the
    test user's account, so it leaves nothing behind and can run repeatedly.
    """

    params = {"country_id": COUNTRY_ID}
    legacy_policy_id = _v1_id(api_client, "policy", {"data": {}}, "policy_id")
    converted_browser = _browser_headers()
    merged_browser = _browser_headers()
    signed_out_only_browser = _browser_headers()
    # The upgrade must convert, so no account may exist for the test user yet.
    _delete_account(api_client, user_headers)
    try:
        # Reads never create an unauthenticated user.
        absent = api_client.get("/v2/me", params=params, headers=converted_browser)
        assert absent.status_code == 404, absent.text[:500]
        assert _policy_ids(api_client, converted_browser) == set()

        saved = _save_policy(api_client, converted_browser, legacy_policy_id)
        assert saved["user_id"] == converted_browser[UNAUTHENTICATED_USER_HEADER]
        detail = api_client.get(
            f"/v2/user-policies/{saved['id']}",
            params=params,
            headers=converted_browser,
        )
        assert detail.status_code == 200, detail.text[:500]
        assert detail.json()["result"]["item"] == saved
        me = api_client.get("/v2/me", params=params, headers=converted_browser)
        assert me.status_code == 200, me.text[:500]
        assert me.json()["result"]["item"]["user_type"] == "unauthenticated"
        assert me.json()["result"]["item"]["primary_country"] is None
        edited = api_client.patch(
            "/v2/me",
            params=params,
            headers=converted_browser,
            json={"first_name": "Signed out"},
        )
        assert edited.status_code == 403, edited.text[:500]

        # A signed-out browser's work is invisible to the signed-in user...
        other_work = _save_policy(api_client, signed_out_only_browser, legacy_policy_id)
        assert other_work["id"] not in _policy_ids(api_client, user_headers)

        # ...until sign-in converts this browser's user in place. The bearer
        # GET above provisioned the account, so delete it again first.
        _delete_account(api_client, user_headers)
        converted = api_client.post(
            "/v2/me/upgrade",
            params=params,
            headers={**user_headers, **converted_browser},
        )
        assert converted.status_code == 200, converted.text[:500]
        converted_result = converted.json()["result"]
        assert converted_result["outcome"] == "converted"
        account_id = converted_result["item"]["id"]
        assert account_id == converted_browser[UNAUTHENTICATED_USER_HEADER]
        assert converted_result["item"]["user_type"] == "standard"
        assert _policy_ids(api_client, user_headers) == {saved["id"]}
        refused = api_client.get("/v2/me", params=params, headers=converted_browser)
        assert refused.status_code == 401, refused.text[:500]

        # A second browser's work merges into the existing account unchanged.
        merged_work = _save_policy(api_client, merged_browser, legacy_policy_id)
        merged = api_client.post(
            "/v2/me/upgrade",
            params=params,
            headers={**user_headers, **merged_browser},
        )
        assert merged.status_code == 200, merged.text[:500]
        assert merged.json()["result"]["outcome"] == "merged"
        assert merged.json()["result"]["item"]["id"] == account_id
        assert _policy_ids(api_client, user_headers) == {saved["id"], merged_work["id"]}
        gone = api_client.get("/v2/me", params=params, headers=merged_browser)
        assert gone.status_code == 404, gone.text[:500]

        repeated = api_client.post(
            "/v2/me/upgrade",
            params=params,
            headers={**user_headers, **merged_browser},
        )
        assert repeated.status_code == 200, repeated.text[:500]
        assert repeated.json()["result"]["outcome"] == "none"

        # A signed-out browser can delete its own work, and nothing else.
        _delete_account(api_client, signed_out_only_browser)
        assert _policy_ids(api_client, signed_out_only_browser) == set()
        assert _policy_ids(api_client, user_headers) == {saved["id"], merged_work["id"]}
    finally:
        _delete_account(api_client, signed_out_only_browser)
        _delete_account(api_client, merged_browser)
        _delete_account(api_client, user_headers)
