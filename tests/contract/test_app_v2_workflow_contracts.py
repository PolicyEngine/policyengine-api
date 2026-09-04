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
        "household_save_edit_read",
        "household_calculate",
        "region_selection",
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
                "metadata_resources_v2_preview",
                "policy_resources_v2",
                "user_policy_associations_v2",
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
