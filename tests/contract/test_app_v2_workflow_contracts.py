from policyengine_api.migration_registry import ROUTE_GROUP_CONFIG_BY_NAME
from tests.contract.registry import (
    APP_V1_COMPATIBLE_ROUTE_CONTRACTS,
    APP_V2_ROUTE_CONTRACTS,
    APP_V2_WORKFLOW_CONTRACTS,
)


def test_app_v2_workflow_contract_registry_is_complete():
    assert {workflow.name for workflow in APP_V2_WORKFLOW_CONTRACTS} == {
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
        "country_selection_v2",
        "economy_reports_v2",
        "metadata_resources_v2_preview",
        "simulation_submit_poll",
        "report_create_poll",
        "budget_window_submit_poll",
    }

    for workflow in APP_V2_WORKFLOW_CONTRACTS:
        expected_contract = (
            "typed_v2_resources"
            if workflow.name
            in {
                "country_selection_v2",
                "economy_reports_v2",
                "metadata_resources_v2_preview",
                "policy_resources_v2",
                "user_policy_associations_v2",
                "household_resources_v2",
                "user_household_associations_v2",
                "user_simulation_associations_v2",
                "user_report_associations_v2",
                "user_account_v2",
            }
            else "api_v1_compatible"
        )
        assert workflow.current_contract == expected_contract
        assert workflow.future_owner_pr
        assert workflow.requests

    for request in APP_V2_ROUTE_CONTRACTS:
        assert request.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert request.path.startswith("/")
        assert request.expected_status in {200, 201, 202, 204}
        assert request.stable_response_fields or request.expected_status == 204
        assert request.route_group in ROUTE_GROUP_CONFIG_BY_NAME
        if request.path.startswith(("/v2/me", "/v2/user-")):
            assert request.headers in {
                ("Authorization",),
                ("PolicyEngine-Unauthenticated-User",),
                ("Authorization", "PolicyEngine-Unauthenticated-User"),
            }
            assert "user_id" not in request.path
        else:
            assert request.headers == ()

    assert all(
        not request.path.startswith("/v2/")
        for request in APP_V1_COMPATIBLE_ROUTE_CONTRACTS
    )
    assert {request.path for request in APP_V2_ROUTE_CONTRACTS} - {
        request.path for request in APP_V1_COMPATIBLE_ROUTE_CONTRACTS
    } == {
        request.path
        for workflow in APP_V2_WORKFLOW_CONTRACTS
        if workflow.current_contract == "typed_v2_resources"
        for request in workflow.requests
    }


def test_user_routes_record_signed_in_and_signed_out_contracts() -> None:
    user_requests = {
        (request.method, request.path.split("?", 1)[0], request.headers)
        for request in APP_V2_ROUTE_CONTRACTS
        if request.path.startswith(("/v2/me", "/v2/user-"))
    }
    signed_out = {
        (method, path)
        for method, path, headers in user_requests
        if headers == ("PolicyEngine-Unauthenticated-User",)
    }

    for resource in ("policies", "households", "simulations", "reports"):
        collection = f"/v2/user-{resource}"
        detail = f"{collection}/{{association_id}}"
        assert {
            ("POST", collection),
            ("GET", collection),
            ("GET", detail),
            ("PATCH", detail),
            ("DELETE", detail),
        } <= signed_out
    assert {("GET", "/v2/me"), ("GET", "/v2/me/export"), ("DELETE", "/v2/me")} <= (
        signed_out
    )
    # Signed-out browsers cannot edit account details.
    assert ("PATCH", "/v2/me") not in signed_out
    assert (
        "POST",
        "/v2/me/upgrade",
        ("Authorization", "PolicyEngine-Unauthenticated-User"),
    ) in user_requests
    assert not any(
        "/v2/me/imports" in path for _method, path, _headers in user_requests
    )


def test_shared_reports_are_read_without_a_credential() -> None:
    shared_reads = [
        request
        for request in APP_V2_ROUTE_CONTRACTS
        if request.path.startswith("/v2/shared-reports/")
    ]

    assert [(request.method, request.headers) for request in shared_reads] == [
        ("GET", ())
    ]
    # The owner and the owner's saved-reform IDs stay private.
    assert not {
        "result.item.user_id",
        "result.item.user_policy_id",
        "result.item.baseline_user_policy_id",
    } & set(shared_reads[0].stable_response_fields)
