from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractRequest:
    method: str
    path: str
    expected_status: int
    stable_response_fields: tuple[str, ...]
    route_group: str
    optional_stable_response_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowContract:
    name: str
    current_contract: str
    future_owner_pr: str
    requests: tuple[ContractRequest, ...]


EXECUTION_RECEIPT_RESPONSE_FIELDS = (
    "execution_receipt.schema_version",
    "execution_receipt.resolved.runtime.name",
    "execution_receipt.resolved.numeric_mode",
    "execution_receipt.resolved.model.actual.version",
    "execution_receipt.resolved.model.certified.version",
    "execution_receipt.request_sha256",
    "execution_receipt.result_sha256",
)


APP_V2_WORKFLOW_CONTRACTS: tuple[WorkflowContract, ...] = (
    WorkflowContract(
        name="policy_save_search",
        current_contract="api_v1_compatible",
        future_owner_pr="PR 10: Policy Migration",
        requests=(
            ContractRequest(
                method="POST",
                path="/us/policy",
                expected_status=201,
                stable_response_fields=("status", "message", "result.policy_id"),
                route_group="policy",
            ),
            ContractRequest(
                method="GET",
                path="/us/policy/{policy_id}",
                expected_status=200,
                stable_response_fields=("status", "message", "result"),
                route_group="policy",
            ),
            ContractRequest(
                method="GET",
                path="/us/policies",
                expected_status=200,
                stable_response_fields=("result",),
                route_group="policy",
            ),
        ),
    ),
    WorkflowContract(
        name="household_save_edit_read",
        current_contract="api_v1_compatible",
        future_owner_pr="PR 11: Household Migration",
        requests=(
            ContractRequest(
                method="POST",
                path="/us/household",
                expected_status=201,
                stable_response_fields=("status", "message", "result.household_id"),
                route_group="household",
            ),
            ContractRequest(
                method="PUT",
                path="/us/household/{household_id}",
                expected_status=200,
                stable_response_fields=("status", "message", "result.household_id"),
                route_group="household",
            ),
            ContractRequest(
                method="GET",
                path="/us/household/{household_id}",
                expected_status=200,
                stable_response_fields=("status", "message", "result"),
                route_group="household",
            ),
        ),
    ),
    WorkflowContract(
        name="household_calculate",
        current_contract="api_v1_compatible",
        future_owner_pr="PR 13: Household Calculation Compute Cutover",
        requests=(
            ContractRequest(
                method="POST",
                path="/us/calculate",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result",
                ),
                route_group="household",
                optional_stable_response_fields=EXECUTION_RECEIPT_RESPONSE_FIELDS,
            ),
            ContractRequest(
                method="GET",
                path="/us/household/{household_id}/policy/{policy_id}",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result",
                ),
                route_group="household",
                optional_stable_response_fields=EXECUTION_RECEIPT_RESPONSE_FIELDS,
            ),
        ),
    ),
    WorkflowContract(
        name="region_selection",
        current_contract="api_v1_compatible",
        future_owner_pr="PR 9: v2 Metadata, Regions, Datasets, Parameters, and Variables",
        requests=(
            ContractRequest(
                method="GET",
                path="/us/metadata",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "result.current_law_id",
                    "result.economy_options.region",
                    "result.economy_options.time_period",
                ),
                route_group="metadata",
            ),
            ContractRequest(
                method="GET",
                path="/uk/metadata",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "result.current_law_id",
                    "result.economy_options.region",
                    "result.economy_options.time_period",
                ),
                route_group="metadata",
            ),
        ),
    ),
    WorkflowContract(
        name="simulation_submit_poll",
        current_contract="api_v1_compatible",
        future_owner_pr="PR 13: Household Calculation Compute Cutover",
        requests=(
            ContractRequest(
                method="POST",
                path="/us/simulation",
                expected_status=201,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.id",
                    "result.status",
                ),
                route_group="simulation",
            ),
            ContractRequest(
                method="GET",
                path="/us/simulation/{simulation_id}",
                expected_status=200,
                stable_response_fields=("status", "message", "result"),
                route_group="simulation",
            ),
        ),
    ),
    WorkflowContract(
        name="report_create_poll",
        current_contract="api_v1_compatible",
        future_owner_pr="PR 14: Economy Simulation and Economic Impact Compute Cutover",
        requests=(
            ContractRequest(
                method="POST",
                path="/us/report",
                expected_status=201,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.id",
                    "result.status",
                ),
                route_group="report",
            ),
            ContractRequest(
                method="GET",
                path="/us/report/{report_id}",
                expected_status=200,
                stable_response_fields=("status", "message", "result"),
                route_group="report",
            ),
        ),
    ),
    WorkflowContract(
        name="budget_window_submit_poll",
        current_contract="api_v1_compatible",
        future_owner_pr="PR 15: Budget-Window and Remaining Simulation API Migration",
        requests=(
            ContractRequest(
                method="GET",
                path="/us/economy/{policy_id}/over/{baseline_policy_id}/budget-window?region=us&start_year=2026&window_size=1",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "result.kind",
                    "progress",
                    "completed_years",
                    "computing_years",
                    "queued_years",
                    "error",
                ),
                route_group="economy",
            ),
        ),
    ),
)

APP_V2_ROUTE_CONTRACTS = tuple(
    request for workflow in APP_V2_WORKFLOW_CONTRACTS for request in workflow.requests
)
