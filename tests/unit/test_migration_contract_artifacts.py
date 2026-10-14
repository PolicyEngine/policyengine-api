import json
from collections import Counter

import pytest

from scripts import export_migration_contracts
from scripts.guards import migration_contracts


def test_migration_contract_payload_summarizes_route_contracts():
    payload = export_migration_contracts.build_payload()

    assert payload["version"] == 1
    assert payload["metadata"] == {
        "route_group_count": 9,
        "workflow_count": 16,
        "request_count": 89,
        "db_entity_count": 6,
        "sim_flow_count": 3,
    }
    assert {workflow["name"] for workflow in payload["workflows"]} == {
        "policy_save_search",
        "policy_resources_v2",
        "saved_policy_v1_compatibility",
        "user_policy_associations_v2",
        "household_save_read",
        "household_resources_v2",
        "user_household_associations_v2",
        "user_simulation_associations_v2",
        "user_report_associations_v2",
        "user_account_v2",
        "household_calculate",
        "region_selection",
        "metadata_resources_v2_preview",
        "simulation_submit_poll",
        "report_create_poll",
        "budget_window_submit_poll",
    }


def test_generated_migration_contract_json_is_current():
    payload = export_migration_contracts.build_payload()

    assert json.loads(export_migration_contracts.DEFAULT_JSON.read_text()) == payload


def test_generated_migration_contract_markdown_is_current():
    payload = export_migration_contracts.build_payload()

    assert export_migration_contracts.DEFAULT_MARKDOWN.read_text() == (
        export_migration_contracts.render_markdown(payload)
    )


def test_migration_contract_quality_guard_passes():
    assert migration_contracts.check() == []


def test_migration_contract_quality_guard_rejects_duplicate_path_segments(
    monkeypatch,
):
    payload = export_migration_contracts.build_payload()
    duplicate_group = {
        **payload["route_groups"][0],
        "name": "duplicate_metadata",
    }
    monkeypatch.setattr(
        export_migration_contracts,
        "build_payload",
        lambda: {
            **payload,
            "route_groups": [*payload["route_groups"], duplicate_group],
        },
    )

    assert any(
        "duplicate route path segment" in violation
        for violation in migration_contracts.check()
    )


def _payload_with_user_report_headers(headers: list[str]) -> dict:
    payload = export_migration_contracts.build_payload()
    workflows = [
        {
            **workflow,
            "requests": [
                {**request, "headers": headers} for request in workflow["requests"]
            ],
        }
        if workflow["name"] == "user_report_associations_v2"
        else workflow
        for workflow in payload["workflows"]
    ]
    return {**payload, "workflows": workflows}


@pytest.mark.parametrize("headers", [[], ["Content-Type"]])
def test_migration_contract_quality_guard_requires_a_user_route_credential(
    monkeypatch, headers: list[str]
):
    payload = _payload_with_user_report_headers(headers)
    monkeypatch.setattr(export_migration_contracts, "build_payload", lambda: payload)

    violations = migration_contracts.check()

    assert any(
        "user-owned routes must require the Authorization or "
        "PolicyEngine-Unauthenticated-User header" in violation
        for violation in violations
    )


def test_migration_contract_quality_guard_keys_requests_by_credential(
    monkeypatch,
):
    payload = _payload_with_user_report_headers(["Authorization"])
    monkeypatch.setattr(export_migration_contracts, "build_payload", lambda: payload)

    violations = migration_contracts.check()

    # The signed-out variants now duplicate the signed-in ones exactly.
    assert any(
        "duplicate contract request: 'POST /v2/user-reports?country_id=us "
        "Authorization'" in violation
        for violation in violations
    )
    assert not any("must require" in violation for violation in violations)


def test_user_contracts_require_a_signed_in_or_signed_out_credential():
    payload = export_migration_contracts.build_payload()
    user_requests = [
        request
        for workflow in payload["workflows"]
        for request in workflow["requests"]
        if request["path"].startswith(("/v2/me", "/v2/user-"))
    ]
    headers_by_request = Counter(tuple(request["headers"]) for request in user_requests)

    assert headers_by_request == {
        ("Authorization",): 24,
        ("PolicyEngine-Unauthenticated-User",): 23,
        ("Authorization", "PolicyEngine-Unauthenticated-User"): 1,
    }
    assert all("user_id=" not in request["path"] for request in user_requests)


def _contract_request(path, status, fields, *, route_group="metadata"):
    return {
        "method": "GET",
        "path": path,
        "route_group": route_group,
        "expected_status": status,
        "stable_response_fields": fields,
    }


def test_workflow_guard_reports_each_request_problem_in_order():
    payload = {
        "route_groups": [{"name": "metadata"}],
        "workflows": [
            {
                "name": "read",
                "current_contract": "api_v1_compatible",
                "future_owner_pr": "PR 9",
                "requests": [
                    _contract_request("/us/metadata", 200, ["result"]),
                    _contract_request("/us/deleted", 204, []),
                    _contract_request("/us/empty", 200, []),
                    _contract_request(
                        "us/no-slash", 201, ["result"], route_group="unknown"
                    ),
                    _contract_request("/us/teapot", 418, ["result"]),
                    _contract_request("/us/metadata", 202, ["result"]),
                ],
            },
            {
                "name": "read",
                "current_contract": "legacy",
                "future_owner_pr": "",
                "requests": [],
            },
        ],
    }

    assert migration_contracts._check_workflows(payload) == [
        "duplicate workflow: 'read'",
        "read GET /us/empty: stable_response_fields is required",
        "read GET us/no-slash: unknown route_group 'unknown'",
        "read GET us/no-slash: path must start with /",
        "read GET /us/teapot: unexpected status 418",
        "read: current_contract is not recognized",
        "read: future_owner_pr is required",
        "read: at least one request is required",
        "duplicate contract request: 'GET /us/metadata'",
    ]
