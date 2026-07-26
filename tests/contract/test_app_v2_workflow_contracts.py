from policyengine_api.migration_registry import ROUTE_GROUP_CONFIG_BY_NAME
from tests.contract.registry import APP_V2_ROUTE_CONTRACTS, APP_V2_WORKFLOW_CONTRACTS


def test_app_v2_workflow_contract_registry_is_complete():
    assert {workflow.name for workflow in APP_V2_WORKFLOW_CONTRACTS} == {
        "policy_save_search",
        "household_save_edit_read",
        "household_calculate",
        "region_selection",
        "simulation_submit_poll",
        "report_create_poll",
        "budget_window_submit_poll",
    }

    for workflow in APP_V2_WORKFLOW_CONTRACTS:
        assert workflow.current_contract == "api_v1_compatible"
        assert workflow.future_owner_pr
        assert workflow.requests

    for request in APP_V2_ROUTE_CONTRACTS:
        assert request.method in {"GET", "POST", "PUT", "PATCH"}
        assert request.path.startswith("/")
        assert request.expected_status in {200, 201, 202}
        assert request.stable_response_fields
        assert not set(request.stable_response_fields) & set(
            request.optional_stable_response_fields
        )
        assert request.route_group in ROUTE_GROUP_CONFIG_BY_NAME
