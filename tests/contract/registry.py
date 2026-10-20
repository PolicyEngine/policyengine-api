from __future__ import annotations

from dataclasses import dataclass

AUTHORIZATION_HEADER = "Authorization"
UNAUTHENTICATED_USER_HEADER = "PolicyEngine-Unauthenticated-User"
USER_AUTH_HEADERS = (AUTHORIZATION_HEADER,)
UNAUTHENTICATED_USER_HEADERS = (UNAUTHENTICATED_USER_HEADER,)
# Each user-owned request is recorded once per credential that can make it.
ACCOUNT_CREDENTIAL_HEADERS = (USER_AUTH_HEADERS, UNAUTHENTICATED_USER_HEADERS)


@dataclass(frozen=True)
class ContractRequest:
    method: str
    path: str
    expected_status: int
    stable_response_fields: tuple[str, ...]
    route_group: str
    # Request headers the route requires, by name. User-owned routes require
    # "Authorization: Bearer <Auth0 user access token>" from a signed-in user,
    # or "PolicyEngine-Unauthenticated-User: <browser UUID>" from a
    # signed-out browser.
    headers: tuple[str, ...] = ()


def _association_item_fields(*names: str) -> tuple[str, ...]:
    return (
        "status",
        "message",
        "result.item.id",
        "result.item.country_id",
        "result.item.user_id",
        *(f"result.item.{name}" for name in names),
        "result.item.created_at",
        "result.item.updated_at",
    )


PAGE_FIELDS = (
    "status",
    "message",
    "result.items",
    "result.offset",
    "result.limit",
    "result.has_more",
)


def _association_requests(
    resource: str,
    *,
    route_group: str,
    item_fields: tuple[str, ...],
    patch_fields: tuple[str, ...],
    headers: tuple[str, ...],
) -> tuple[ContractRequest, ...]:
    detail_path = f"/v2/{resource}/{{association_id}}?country_id=us"
    return (
        ContractRequest(
            method="POST",
            path=f"/v2/{resource}?country_id=us",
            expected_status=201,
            stable_response_fields=item_fields,
            route_group=route_group,
            headers=headers,
        ),
        ContractRequest(
            method="GET",
            path=detail_path,
            expected_status=200,
            stable_response_fields=item_fields,
            route_group=route_group,
            headers=headers,
        ),
        ContractRequest(
            method="GET",
            path=f"/v2/{resource}?country_id=us",
            expected_status=200,
            stable_response_fields=PAGE_FIELDS,
            route_group=route_group,
            headers=headers,
        ),
        ContractRequest(
            method="PATCH",
            path=detail_path,
            expected_status=200,
            stable_response_fields=(
                "status",
                "message",
                "result.item.id",
                *(f"result.item.{name}" for name in patch_fields),
                "result.item.updated_at",
            ),
            route_group=route_group,
            headers=headers,
        ),
        ContractRequest(
            method="DELETE",
            path=detail_path,
            expected_status=204,
            stable_response_fields=(),
            route_group=route_group,
            headers=headers,
        ),
    )


def _user_association_requests(
    resource: str,
    *,
    route_group: str,
    item_fields: tuple[str, ...],
    patch_fields: tuple[str, ...],
) -> tuple[ContractRequest, ...]:
    return tuple(
        request
        for headers in ACCOUNT_CREDENTIAL_HEADERS
        for request in _association_requests(
            resource,
            route_group=route_group,
            item_fields=item_fields,
            patch_fields=patch_fields,
            headers=headers,
        )
    )


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
        future_owner_pr="PR 12A: User Login and v1-Anchored User Associations",
        requests=_user_association_requests(
            "user-policies",
            route_group="policy",
            item_fields=_association_item_fields(
                "policy_id",
                "legacy_policy_id",
                "name",
                "description",
                "baseline",
                "provenance",
            ),
            patch_fields=(
                "legacy_policy_id",
                "policy_id",
                "name",
                "description",
                "baseline",
                "provenance",
            ),
        ),
    ),
    WorkflowContract(
        name="household_save_read",
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
                method="GET",
                path="/us/household/{household_id}",
                expected_status=200,
                stable_response_fields=("status", "message", "result"),
                route_group="household",
            ),
        ),
    ),
    WorkflowContract(
        name="household_resources_v2",
        current_contract="typed_v2_resources",
        future_owner_pr="PR 11: Household Migration",
        requests=(
            ContractRequest(
                method="POST",
                path="/v2/households?country_id=us",
                expected_status=201,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.country_id",
                    "result.item.default_year",
                    "result.item.household_data",
                    "result.item.created_at",
                    "result.item.updated_at",
                ),
                route_group="household",
            ),
            ContractRequest(
                method="GET",
                path="/v2/households/{household_id}?country_id=us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.country_id",
                    "result.item.default_year",
                    "result.item.household_data",
                    "result.item.created_at",
                    "result.item.updated_at",
                ),
                route_group="household",
            ),
            ContractRequest(
                method="GET",
                path="/v2/households?country_id=us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.items",
                    "result.offset",
                    "result.limit",
                    "result.has_more",
                ),
                route_group="household",
            ),
        ),
    ),
    WorkflowContract(
        name="user_household_associations_v2",
        current_contract="typed_v2_resources",
        future_owner_pr="PR 12A: User Login and v1-Anchored User Associations",
        requests=_user_association_requests(
            "user-households",
            route_group="household",
            item_fields=_association_item_fields(
                "household_id",
                "legacy_household_id",
                "name",
                "description",
            ),
            patch_fields=(
                "legacy_household_id",
                "household_id",
                "name",
                "description",
            ),
        ),
    ),
    WorkflowContract(
        name="user_simulation_associations_v2",
        current_contract="typed_v2_resources",
        future_owner_pr="PR 12A: User Login and v1-Anchored User Associations",
        requests=_user_association_requests(
            "user-simulations",
            route_group="simulation",
            item_fields=_association_item_fields(
                "simulation_id",
                "legacy_simulation_id",
                "name",
                "description",
            ),
            patch_fields=("legacy_simulation_id", "name", "description"),
        ),
    ),
    WorkflowContract(
        name="user_report_associations_v2",
        current_contract="typed_v2_resources",
        future_owner_pr="PR 12A: User Login and v1-Anchored User Associations",
        requests=(
            *_user_association_requests(
                "user-reports",
                route_group="report",
                item_fields=_association_item_fields(
                    "report_id",
                    "legacy_report_id",
                    "name",
                    "description",
                    "user_policy_id",
                    "baseline_user_policy_id",
                    "source_note",
                    "provisions",
                    "validation",
                    "budget_window_years",
                    "last_run_at",
                ),
                patch_fields=(
                    "legacy_report_id",
                    "name",
                    "description",
                    "user_policy_id",
                    "baseline_user_policy_id",
                    "source_note",
                    "provisions",
                    "validation",
                    "budget_window_years",
                    "last_run_at",
                ),
            ),
            # A saved report's ID is its shareable link: anyone can read it,
            # with no credential, minus the owner and the owner's links.
            ContractRequest(
                method="GET",
                path="/v2/shared-reports/{association_id}?country_id=us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.country_id",
                    "result.item.legacy_report_id",
                    "result.item.name",
                    "result.item.source_note",
                    "result.item.provisions",
                    "result.item.validation",
                    "result.item.budget_window_years",
                    "result.item.baseline_reform",
                    "result.item.last_run_at",
                    "result.item.created_at",
                    "result.item.updated_at",
                ),
                route_group="report",
            ),
        ),
    ),
    WorkflowContract(
        name="user_account_v2",
        current_contract="typed_v2_resources",
        future_owner_pr="PR 12A: User Login and v1-Anchored User Associations",
        requests=(
            *(
                ContractRequest(
                    method="GET",
                    path="/v2/me?country_id=us",
                    expected_status=200,
                    stable_response_fields=(
                        "status",
                        "message",
                        "result.item.id",
                        "result.item.user_type",
                        "result.item.primary_country",
                        "result.item.first_name",
                        "result.item.last_name",
                        "result.item.email",
                        "result.item.created_at",
                    ),
                    route_group="user_profile",
                    headers=headers,
                )
                for headers in ACCOUNT_CREDENTIAL_HEADERS
            ),
            ContractRequest(
                method="PATCH",
                path="/v2/me?country_id=us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.primary_country",
                    "result.item.first_name",
                    "result.item.last_name",
                ),
                route_group="user_profile",
                headers=USER_AUTH_HEADERS,
            ),
            *(
                ContractRequest(
                    method="GET",
                    path="/v2/me/export?country_id=us",
                    expected_status=200,
                    stable_response_fields=(
                        "status",
                        "message",
                        "result.user",
                        "result.policies",
                        "result.households",
                        "result.simulations",
                        "result.reports",
                    ),
                    route_group="user_profile",
                    headers=headers,
                )
                for headers in ACCOUNT_CREDENTIAL_HEADERS
            ),
            ContractRequest(
                method="POST",
                path="/v2/me/upgrade?country_id=us",
                expected_status=200,
                stable_response_fields=(
                    "status",
                    "message",
                    "result.item.id",
                    "result.item.user_type",
                    "result.item.primary_country",
                    "result.outcome",
                ),
                route_group="user_profile",
                headers=(AUTHORIZATION_HEADER, UNAUTHENTICATED_USER_HEADER),
            ),
            *(
                ContractRequest(
                    method="DELETE",
                    path="/v2/me?country_id=us",
                    expected_status=204,
                    stable_response_fields=(),
                    route_group="user_profile",
                    headers=headers,
                )
                for headers in ACCOUNT_CREDENTIAL_HEADERS
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
        future_owner_pr=(
            "PR 9: v2 Metadata, Regions, Datasets, Parameters, and Variables"
        ),
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
