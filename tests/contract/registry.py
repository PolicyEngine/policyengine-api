from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractRequest:
    method: str
    path: str
    expected_status: int
    stable_response_fields: tuple[str, ...]
    route_group: str


@dataclass(frozen=True)
class WorkflowContract:
    name: str
    current_contract: str
    future_owner_pr: str
    requests: tuple[ContractRequest, ...]


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
        name="policy_resources_v2",
        current_contract="typed_v2_resources",
        future_owner_pr="PR 10: Policy Migration",
        requests=(
            ContractRequest(
                method="POST",
                path="/v2/policies?country_id=us",
                expected_status=201,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.country_id",
                    "result.item.tax_benefit_model_id",
                    "result.item.parameter_values",
                    "result.item.created_at",
                    "result.item.updated_at",
                ),
                route_group="policy",
            ),
            ContractRequest(
                method="GET",
                path="/v2/policies/{policy_id}?country_id=us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.country_id",
                    "result.item.tax_benefit_model_id",
                    "result.item.parameter_values",
                    "result.item.created_at",
                    "result.item.updated_at",
                ),
                route_group="policy",
            ),
            ContractRequest(
                method="GET",
                path="/v2/policies?country_id=us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.items",
                    "result.offset",
                    "result.limit",
                    "result.has_more",
                ),
                route_group="policy",
            ),
        ),
    ),
    WorkflowContract(
        name="saved_policy_v1_compatibility",
        current_contract="api_v1_compatible",
        future_owner_pr="PR 10: Policy Migration",
        requests=(
            ContractRequest(
                method="POST",
                path="/us/user-policy",
                expected_status=201,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.id",
                    "result.reform_id",
                    "result.reform_label",
                    "result.baseline_id",
                    "result.user_id",
                ),
                route_group="policy",
            ),
            ContractRequest(
                method="GET",
                path="/us/user-policy/{user_id}",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result",
                ),
                route_group="policy",
            ),
            ContractRequest(
                method="PUT",
                path="/us/user-policy",
                expected_status=200,
                stable_response_fields=("status", "message", "result.id"),
                route_group="policy",
            ),
        ),
    ),
    WorkflowContract(
        name="user_policy_associations_v2",
        current_contract="typed_v2_resources",
        future_owner_pr="PR 10: Policy Migration",
        requests=(
            ContractRequest(
                method="POST",
                path="/v2/user-policies?country_id=us",
                expected_status=201,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.country_id",
                    "result.item.user_id",
                    "result.item.policy_id",
                    "result.item.name",
                    "result.item.description",
                    "result.item.created_at",
                    "result.item.updated_at",
                ),
                route_group="policy",
            ),
            ContractRequest(
                method="GET",
                path=("/v2/user-policies/{association_id}?country_id=us"),
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.country_id",
                    "result.item.user_id",
                    "result.item.policy_id",
                    "result.item.name",
                    "result.item.description",
                    "result.item.created_at",
                    "result.item.updated_at",
                ),
                route_group="policy",
            ),
            ContractRequest(
                method="GET",
                path="/v2/user-policies?country_id=us&user_id=caller",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.items",
                    "result.offset",
                    "result.limit",
                    "result.has_more",
                ),
                route_group="policy",
            ),
            ContractRequest(
                method="PATCH",
                path=("/v2/user-policies/{association_id}?country_id=us"),
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.name",
                    "result.item.description",
                    "result.item.updated_at",
                ),
                route_group="policy",
            ),
            ContractRequest(
                method="DELETE",
                path=("/v2/user-policies/{association_id}?country_id=us"),
                expected_status=204,
                stable_response_fields=(),
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
                stable_response_fields=("status", "message", "result"),
                route_group="household",
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
        name="metadata_resources_v2_preview",
        current_contract="typed_v2_resources",
        future_owner_pr="Later metadata read cutover and v2 route-prefix removal",
        requests=(
            *(
                ContractRequest(
                    method="GET",
                    path=path,
                    expected_status=200,
                    stable_response_fields=(
                        "status",
                        "message",
                        "result.policyengine_version",
                        "result.items",
                        "result.offset",
                        "result.limit",
                        "result.has_more",
                    ),
                    route_group="metadata",
                )
                for path in (
                    "/v2/tax-benefit-models?country_id=us",
                    "/v2/tax-benefit-model-versions?country_id=us",
                    "/v2/variables?country_id=us",
                    "/v2/parameters?country_id=us",
                    "/v2/parameters/children?country_id=us&parent_path=gov",
                    "/v2/parameter-values?country_id=us",
                    "/v2/datasets?country_id=us",
                    "/v2/regions?country_id=us",
                )
            ),
            *(
                ContractRequest(
                    method="GET",
                    path=path,
                    expected_status=200,
                    stable_response_fields=(
                        "status",
                        "message",
                        "result.policyengine_version",
                        "result.item",
                    ),
                    route_group="metadata",
                )
                for path in (
                    "/v2/tax-benefit-models/{model_id}?country_id=us",
                    "/v2/tax-benefit-model-versions/{version_id}?country_id=us",
                    "/v2/variables/{variable_id}?country_id=us",
                    "/v2/parameters/{parameter_id}?country_id=us",
                    "/v2/parameter-values/{value_id}?country_id=us",
                    "/v2/datasets/{dataset_id}?country_id=us",
                    "/v2/regions/{region_id}?country_id=us",
                    "/v2/regions/by-code/state/ca?country_id=us",
                )
            ),
            ContractRequest(
                method="GET",
                path="/v2/tax-benefit-models/by-country/us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.policyengine_version",
                    "result.model",
                    "result.model_version",
                ),
                route_group="metadata",
            ),
            ContractRequest(
                method="GET",
                path="/v2/economy-options?country_id=us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.policyengine_version",
                    "result.current_law_id",
                    "result.region",
                    "result.time_period",
                    "result.datasets",
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

APP_V1_COMPATIBLE_ROUTE_CONTRACTS = tuple(
    request
    for workflow in APP_V2_WORKFLOW_CONTRACTS
    if workflow.current_contract == "api_v1_compatible"
    for request in workflow.requests
)
