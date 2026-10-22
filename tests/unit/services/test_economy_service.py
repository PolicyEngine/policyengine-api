import json
from dataclasses import replace
from typing import Literal, NamedTuple
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from policyengine_api.libs.simulation_entrypoint import (
    ModalSimulationExecution,
    SimulationRunProgress,
)
from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.runtime_cache.reform_impacts import (
    ReformImpactIdentity,
    ReformImpactScope,
    ReformImpactStartClaim,
)
from policyengine_api.services.budget_window_cache import BudgetWindowCacheState
from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_service import (
    BUDGET_WINDOW_MAX_END_YEAR,
    BUDGET_WINDOW_MAX_YEARS,
    REFORM_IMPACT_START_CLAIM_ATTEMPTS,
    BudgetWindowYearProgress,
    EconomicImpactResult,
    EconomicImpactSetupOptions,
    EconomyService,
    ImpactAction,
    ImpactStatus,
    RuntimeBundleIdentity,
)
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.reform_impacts_service import (
    ReformImpactHandoffError,
)
from policyengine_api.spm import SPMValidationError
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_COUNTRY_ID,
    MOCK_DATA_VERSION,
    MOCK_DATASET,
    MOCK_EXECUTION_ID,
    MOCK_LOOKUP_OPTIONS_HASH,
    MOCK_MODEL_VERSION,
    MOCK_OBSERVABILITY_ID,
    MOCK_OPTIONS,
    MOCK_OPTIONS_HASH,
    MOCK_POLICY_ID,
    MOCK_POLICYENGINE_VERSION,
    MOCK_REFORM_IMPACT_DATA,
    MOCK_REGION,
    MOCK_RESOLVED_APP_NAME,
    MOCK_RESOLVED_DATASET,
    MOCK_SUBMISSION_CLAIM_ID,
    MOCK_TIME_PERIOD,
    MockBatchProgress,
    create_mock_budget_window_batch_execution,
    create_mock_reform_impact,
)
from tests.fixtures.spm import (
    resolved_options,
    worker_result_fields,
    worker_spm_capability,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)


def setup_options_for(country_id: str, region: str) -> EconomicImpactSetupOptions:
    """Return resolved setup options for one country and pre-normalized region."""
    return EconomicImpactSetupOptions(
        submission_claim_id=MOCK_SUBMISSION_CLAIM_ID,
        country_id=country_id,
        reform_policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region=region,
        dataset=MOCK_DATASET,
        time_period=MOCK_TIME_PERIOD,
        options={},
        api_version=MOCK_API_VERSION,
        target="general",
    )


def uk_breakdown_request(
    *,
    country_id: str = "uk",
    region: str = "uk",
    target: Literal["general", "cliff"] = "general",
) -> EconomicImpactRequest:
    """Return an annual request for the UK local-area breakdown."""
    return EconomicImpactRequest(
        country_id=country_id,
        policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region=region,
        dataset="default",
        options={"breakdown": "local_areas"},
        api_version=MOCK_API_VERSION,
        target=target,
    )


class EconomyServiceHarness(NamedTuple):
    """The service under test, its call parameters and the mocks it talks to."""

    service: EconomyService
    params: dict
    reform_impacts_service: MagicMock
    simulation_entrypoint: MagicMock


def hash_prefix_lookup(reform_impacts_service: MagicMock) -> MagicMock:
    """Return the mocked lookup of reform impacts by options-hash prefix."""
    lookup: MagicMock = (
        reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix
    )
    return lookup


@pytest.fixture(autouse=True)
def stable_observability_lifecycle():
    with (
        patch(
            "policyengine_api.services.economy_service.start_observability_id",
            return_value=MOCK_OBSERVABILITY_ID,
        ),
        patch(
            "policyengine_api.services.economy_service.restore_observability_id",
            side_effect=lambda value: value,
        ),
        patch(
            "policyengine_api.services.economy_service.resolve_observability_id",
            return_value=MOCK_OBSERVABILITY_ID,
        ),
    ):
        yield


def make_mock_budget_impact_data(
    *,
    tax_revenue_impact: int,
    state_tax_revenue_impact: int,
    benefit_spending_impact: int,
    budgetary_impact: int,
):
    return {
        "budget": {
            "tax_revenue_impact": tax_revenue_impact,
            "state_tax_revenue_impact": state_tax_revenue_impact,
            "benefit_spending_impact": benefit_spending_impact,
            "budgetary_impact": budgetary_impact,
        }
    }


def make_http_status_error(
    status_code: int,
    payload: dict | None = None,
    text: str | None = None,
) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "POST",
        "https://policyengine-staging--policyengine-simulation-gateway-web-app.modal.run/simulate/economy/budget-window",
    )
    response = (
        httpx.Response(status_code, json=payload, request=request)
        if payload is not None
        else httpx.Response(status_code, text=text or "", request=request)
    )
    return httpx.HTTPStatusError(
        f"Client error '{status_code}'",
        request=request,
        response=response,
    )


def complete_budget_window_result(
    *, annual_values: dict[str, dict] | None = None, totals: dict | None = None
) -> dict:
    years = ("2026", "2027", "2028")
    annual_values = annual_values or {}
    return {
        "kind": "budgetWindow",
        "startYear": years[0],
        "endYear": years[-1],
        "windowSize": len(years),
        "annualImpacts": [
            {
                "year": year,
                **annual_values.get(year, {}),
                **worker_result_fields(years=[year]),
            }
            for year in years
        ],
        "totals": totals or {},
    }


class TestEconomyService:
    class TestGetEconomicImpact:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.fixture
        def base_params(self):
            return {
                "impact_request": EconomicImpactRequest(
                    country_id=MOCK_COUNTRY_ID,
                    policy_id=MOCK_POLICY_ID,
                    baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                    region=MOCK_REGION,
                    dataset=MOCK_DATASET,
                    options=MOCK_OPTIONS,
                    api_version=MOCK_API_VERSION,
                    target="general",
                ),
                "time_period": MOCK_TIME_PERIOD,
            }

        @pytest.fixture
        def economy_service_harness(
            self,
            economy_service: EconomyService,
            base_params: dict,
            mock_reform_impacts_service: MagicMock,
            mock_simulation_entrypoint: MagicMock,
        ) -> EconomyServiceHarness:
            return EconomyServiceHarness(
                service=economy_service,
                params=base_params,
                reform_impacts_service=mock_reform_impacts_service,
                simulation_entrypoint=mock_simulation_entrypoint,
            )

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_completed_impact__returns_completed_result(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert (
                result.data["poverty_impact"]
                == MOCK_REFORM_IMPACT_DATA["poverty_impact"]
            )
            assert result.data["policyengine_bundle"] == {
                "model_version": MOCK_MODEL_VERSION,
                "policyengine_version": MOCK_POLICYENGINE_VERSION,
                "data_version": MOCK_DATA_VERSION,
                "dataset": MOCK_RESOLVED_DATASET,
            }
            (hash_prefix_lookup(mock_reform_impacts_service).assert_called_once())
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_orm_decoded_completed_impact__returns_completed_result(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            completed_impact.reform_impact_json = json.loads(
                completed_impact.reform_impact_json
            )
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert (
                result.data["poverty_impact"]
                == MOCK_REFORM_IMPACT_DATA["poverty_impact"]
            )
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.parametrize(
            ("cached_message", "expected_message"),
            [
                (
                    "Simulation entrypoint execution failed: worker exited",
                    "Simulation entrypoint execution failed: worker exited",
                ),
                (None, "Simulation entrypoint execution failed"),
            ],
        )
        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_cached_error_impact__returns_error_message(
            self,
            cached_message,
            expected_message,
            economy_service_harness,
        ):
            harness = economy_service_harness
            failed_impact = create_mock_reform_impact(
                status="error",
                message=cached_message,
            )
            hash_prefix_lookup(harness.reform_impacts_service).return_value = [
                failed_impact
            ]

            result = harness.service.get_economic_impact(**harness.params)

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.message == expected_message
            harness.simulation_entrypoint.run.assert_not_called()
            harness.simulation_entrypoint.get_execution_by_id.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_legacy_completed_impact__refreshes_cache(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            completed_impact = create_mock_reform_impact(
                status="ok",
                reform_impact_json=json.dumps(MOCK_REFORM_IMPACT_DATA),
                options_hash=MOCK_LOOKUP_OPTIONS_HASH,
            )
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            mock_simulation_entrypoint.resolve_app_name.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_MODEL_VERSION,
                policyengine_version=MOCK_POLICYENGINE_VERSION,
            )
            mock_simulation_entrypoint.run.assert_called_once()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_computing_impact_with_succeeded_execution__returns_completed(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            computing_impact = create_mock_reform_impact(status="computing")
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                computing_impact
            ]
            mock_simulation_entrypoint.get_execution_status.return_value = "complete"
            mock_simulation_entrypoint.get_execution_result.return_value = (
                MOCK_REFORM_IMPACT_DATA
            )

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert (
                result.data["budget_impact"] == MOCK_REFORM_IMPACT_DATA["budget_impact"]
            )
            assert result.data["policyengine_bundle"] == {
                "model_version": MOCK_MODEL_VERSION,
                "policyengine_version": MOCK_POLICYENGINE_VERSION,
                "data_version": MOCK_DATA_VERSION,
                "dataset": MOCK_RESOLVED_DATASET,
            }
            mock_simulation_entrypoint.get_execution_by_id.assert_called_once_with(
                MOCK_EXECUTION_ID
            )
            mock_reform_impacts_service.set_complete_reform_impact.assert_called_once()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_computing_impact_with_failed_execution__returns_error_result(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            computing_impact = create_mock_reform_impact(status="computing")
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                computing_impact
            ]
            mock_simulation_entrypoint.get_execution_status.return_value = "failed"
            mock_simulation_entrypoint.get_execution_by_id.return_value.error = (
                "worker exited"
            )

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert (
                result.message
                == "Simulation entrypoint execution failed: worker exited"
            )
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_computing_impact_with_active_execution__returns_computing(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            computing_impact = create_mock_reform_impact(status="computing")
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                computing_impact
            ]
            mock_simulation_entrypoint.get_execution_status.return_value = "running"

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_no_previous_impact__creates_new_simulation(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            hash_prefix_lookup(mock_reform_impacts_service).return_value = []

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None
            mock_simulation_entrypoint.run.assert_called_once()
            mock_reform_impacts_service.claim_reform_impact_start.assert_called_once()
            assert (
                mock_reform_impacts_service.claim_reform_impact_start.call_args.kwargs[
                    "identity"
                ].options_hash
                == MOCK_OPTIONS_HASH
            )
            mock_reform_impacts_service.release_reform_impact_start.assert_called_once_with(
                **mock_reform_impacts_service.claim_reform_impact_start.call_args.kwargs
            )
            mock_reform_impacts_service.set_reform_impact.assert_called_once()
            write_values = (
                mock_reform_impacts_service.set_reform_impact.call_args.kwargs
            )
            assert write_values["options"] == resolved_options(MOCK_OPTIONS)
            assert write_values["reform_impact_json"] == {}
            assert write_values["execution"].observability_id == MOCK_OBSERVABILITY_ID

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_simulation_entrypoint",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_no_previous_impact__starts_observability_after_claim(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
        ):
            hash_prefix_lookup(mock_reform_impacts_service).return_value = []
            lifecycle_events = []
            mock_reform_impacts_service.claim_reform_impact_start.side_effect = (
                lambda **_kwargs: lifecycle_events.append("claim") or True
            )

            with patch(
                "policyengine_api.services.economy_service.start_observability_id",
                side_effect=lambda _value: (
                    lifecycle_events.append("start") or MOCK_OBSERVABILITY_ID
                ),
            ) as start_observability_id:
                result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            start_observability_id.assert_called_once_with(MOCK_OBSERVABILITY_ID)
            assert lifecycle_events == ["claim", "start"]

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_simulation_entrypoint",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__selected_observability_id_is_applied_to_containing_spans(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
        ):
            hash_prefix_lookup(mock_reform_impacts_service).return_value = []

            with patch(
                "policyengine_api.services.economy_service.set_runtime_context"
            ) as set_runtime_context:
                result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert (
                set_runtime_context.call_args_list.count(
                    call(observability_id=MOCK_OBSERVABILITY_ID)
                )
                == 2
            )

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_existing_start_claim__does_not_submit_duplicate_simulation(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_reform_impacts_service.claim_reform_impact_start.return_value = False
            winning_observability_id = "00000000-0000-4000-8000-000000000003"
            mock_reform_impacts_service.get_reform_impact_start_claim.return_value = (
                ReformImpactStartClaim(
                    submission_claim_id="winning-claim",
                    observability_id=winning_observability_id,
                )
            )

            with patch(
                "policyengine_api.services.economy_service.restore_observability_id",
                return_value=winning_observability_id,
            ) as restore_observability_id:
                result = economy_service.get_economic_impact(**base_params)

            assert result.status is ImpactStatus.COMPUTING
            restore_observability_id.assert_called_once_with(winning_observability_id)
            mock_simulation_entrypoint.run.assert_not_called()
            mock_reform_impacts_service.set_reform_impact.assert_not_called()
            mock_reform_impacts_service.release_reform_impact_start.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_expired_contended_claim__retries_and_submits(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_reform_impacts_service.claim_reform_impact_start.side_effect = [
                False,
                True,
            ]
            mock_reform_impacts_service.get_reform_impact_start_claim.return_value = (
                None
            )

            with patch(
                "policyengine_api.services.economy_service.start_observability_id",
                return_value=MOCK_OBSERVABILITY_ID,
            ) as start_observability_id:
                result = economy_service.get_economic_impact(**base_params)

            assert result.status is ImpactStatus.COMPUTING
            assert mock_reform_impacts_service.claim_reform_impact_start.call_count == 2
            mock_reform_impacts_service.get_reform_impact_start_claim.assert_called_once()
            start_observability_id.assert_called_once_with(MOCK_OBSERVABILITY_ID)
            mock_simulation_entrypoint.run.assert_called_once()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_repeatedly_expiring_start_claims__fails_before_submission(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_reform_impacts_service.claim_reform_impact_start.return_value = False
            mock_reform_impacts_service.get_reform_impact_start_claim.return_value = (
                None
            )

            with (
                patch(
                    "policyengine_api.services.economy_service.start_observability_id"
                ) as start_observability_id,
                pytest.raises(
                    CacheCoordinationError,
                    match="ownership changed repeatedly",
                ),
            ):
                economy_service.get_economic_impact(**base_params)

            assert (
                mock_reform_impacts_service.claim_reform_impact_start.call_count
                == REFORM_IMPACT_START_CLAIM_ATTEMPTS
            )
            assert (
                mock_reform_impacts_service.get_reform_impact_start_claim.call_count
                == REFORM_IMPACT_START_CLAIM_ATTEMPTS
            )
            start_observability_id.assert_not_called()
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_start_claim_cache_failure__fails_before_submission(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_reform_impacts_service.claim_reform_impact_start.side_effect = (
                CacheCoordinationError("cache unavailable")
            )

            with pytest.raises(CacheCoordinationError, match="cache unavailable"):
                economy_service.get_economic_impact(**base_params)

            mock_simulation_entrypoint.run.assert_not_called()
            mock_reform_impacts_service.set_reform_impact.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_gateway_raises_before_returning_execution__releases_start_claim(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_simulation_entrypoint.run.side_effect = RuntimeError(
                "submission failed"
            )

            with pytest.raises(RuntimeError, match="submission failed"):
                economy_service.get_economic_impact(**base_params)

            mock_reform_impacts_service.release_reform_impact_start.assert_called_once_with(
                **mock_reform_impacts_service.claim_reform_impact_start.call_args.kwargs
            )

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_submitted_simulation_handoff_failure__retains_start_claim(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_reform_impacts_service.set_reform_impact.side_effect = (
                ReformImpactHandoffError("cache unavailable")
            )

            with pytest.raises(ReformImpactHandoffError, match="cache unavailable"):
                economy_service.get_economic_impact(**base_params)

            mock_simulation_entrypoint.run.assert_called_once()
            mock_reform_impacts_service.release_reform_impact_start.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_submitted_simulation_without_execution_id__retains_start_claim(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_simulation_entrypoint.get_execution_id.side_effect = RuntimeError(
                "missing execution identifier"
            )

            with pytest.raises(
                ReformImpactHandoffError, match="could not be handed off"
            ):
                economy_service.get_economic_impact(**base_params)

            mock_simulation_entrypoint.run.assert_called_once()
            mock_reform_impacts_service.set_reform_impact.assert_not_called()
            mock_reform_impacts_service.release_reform_impact_start.assert_not_called()

        def test__given_policies_created_through_orm__submits_decoded_json(
            self,
            orm_session_factory,
            monkeypatch,
        ):
            policy_service = PolicyService(orm_session_factory)
            baseline_policy_id, _, _ = policy_service.set_policy(
                "us",
                "ORM baseline",
                {},
            )
            reform = {"gov.example.parameter": {"2026": 1}}
            reform_policy_id, _, _ = policy_service.set_policy(
                "us",
                "ORM reform",
                reform,
            )

            reform_impacts = MagicMock()
            hash_prefix_lookup(reform_impacts).return_value = []
            simulation_gateway = MagicMock()
            simulation_gateway.resolve_app_name.return_value = (
                "policyengine-simulation-test",
                MOCK_MODEL_VERSION,
            )
            simulation_gateway.get_spm_capability.return_value = worker_spm_capability()
            simulation_gateway.get_execution_id.return_value = "execution-1"
            monkeypatch.setattr(
                "policyengine_api.services.economy_service.logger",
                MagicMock(),
            )

            service = EconomyService(
                primary_session_factory=orm_session_factory,
                policy_service_=policy_service,
                reform_impacts_service_=reform_impacts,
                simulation_entrypoint_=simulation_gateway,
            )

            result = service.get_economic_impact(
                EconomicImpactRequest(
                    country_id="us",
                    policy_id=reform_policy_id,
                    baseline_policy_id=baseline_policy_id,
                    region="us",
                    dataset="default",
                    options={},
                    api_version="test",
                ),
                time_period="2026",
            )

            assert result.status is ImpactStatus.COMPUTING
            submitted = simulation_gateway.run.call_args.args[0]
            assert submitted["baseline"] == {}
            assert submitted["reform"] == reform

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_no_previous_impact__includes_metadata_in_simulation_params(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            """Verify that _metadata with policy IDs is passed to simulation API."""
            hash_prefix_lookup(mock_reform_impacts_service).return_value = []

            economy_service.get_economic_impact(**base_params)

            # Get the params passed to simulation_entrypoint.run()
            call_args = mock_simulation_entrypoint.run.call_args
            sim_params = call_args[0][0]  # First positional argument

            # Verify _metadata is included with correct values
            assert "_metadata" in sim_params
            assert sim_params["_metadata"]["reform_policy_id"] == MOCK_POLICY_ID
            assert (
                sim_params["_metadata"]["baseline_policy_id"] == MOCK_BASELINE_POLICY_ID
            )
            assert (
                sim_params["_metadata"]["submission_claim_id"]
                == MOCK_SUBMISSION_CLAIM_ID
            )
            assert sim_params["_metadata"]["model_version"] == MOCK_MODEL_VERSION
            assert (
                sim_params["_metadata"]["policyengine_version"]
                == MOCK_POLICYENGINE_VERSION
            )
            assert sim_params["_metadata"]["data_version"] is None
            assert sim_params["_metadata"]["dataset"] == MOCK_DATASET
            assert "data" not in sim_params
            assert "data_version" not in sim_params
            assert (
                sim_params["_metadata"]["resolved_app_name"] == MOCK_RESOLVED_APP_NAME
            )

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policy_service",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_no_previous_impact__includes_telemetry_in_simulation_params(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
            mock_logger,
        ):
            mock_reform_impacts_service.get_all_reform_impacts.return_value = []

            economy_service.get_economic_impact(**base_params)

            sim_params = mock_simulation_entrypoint.run.call_args[0][0]

            assert "observability_id" not in sim_params["_telemetry"]
            assert (
                sim_params["_telemetry"]["submission_claim_id"]
                == MOCK_SUBMISSION_CLAIM_ID
            )
            assert sim_params["_telemetry"]["simulation_kind"] == "national"
            assert sim_params["_telemetry"]["geography_type"] == "national"
            assert sim_params["_telemetry"]["geography_code"] == MOCK_COUNTRY_ID
            assert sim_params["_telemetry"]["capture_mode"] == "disabled"
            assert sim_params["_telemetry"]["config_hash"].startswith("sha256:")
            progress_log = mock_logger.log_struct.call_args_list[-1].args[0]
            assert progress_log["observability_id"] == MOCK_OBSERVABILITY_ID
            assert (
                mock_logger.log_struct.call_args_list[-1].kwargs["severity"] == "INFO"
            )

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_simulation_entrypoint",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_runtime_cache_version__uses_versioned_economy_cache_key(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            monkeypatch,
        ):
            cache_version = "e1cache01"
            monkeypatch.setattr(
                "policyengine_api.services.economy_service.get_economy_impact_cache_version",
                lambda _country_id, _api_version=None: cache_version,
            )
            hash_prefix_lookup(mock_reform_impacts_service).return_value = []

            economy_service.get_economic_impact(**base_params)

            hash_prefix_lookup(mock_reform_impacts_service).assert_called_once_with(
                ReformImpactIdentity(
                    scope=ReformImpactScope(
                        country_id=MOCK_COUNTRY_ID,
                        reform_policy_id=MOCK_POLICY_ID,
                        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                        region=MOCK_REGION,
                        dataset=MOCK_DATASET,
                        time_period=MOCK_TIME_PERIOD,
                    ),
                    api_version=cache_version,
                    options_hash=MOCK_LOOKUP_OPTIONS_HASH,
                ),
                economy_service._build_options_hash_lookup_pattern(
                    MOCK_LOOKUP_OPTIONS_HASH
                ),
            )

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_simulation_entrypoint",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_default_dataset__queries_previous_impacts_with_resolved_bundle(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
        ):
            hash_prefix_lookup(mock_reform_impacts_service).return_value = []

            economy_service.get_economic_impact(**base_params)

            identity, lookup_pattern = hash_prefix_lookup(
                mock_reform_impacts_service
            ).call_args.args
            assert identity.scope.dataset == MOCK_DATASET
            assert identity.options_hash == MOCK_LOOKUP_OPTIONS_HASH
            assert lookup_pattern == economy_service._build_options_hash_lookup_pattern(
                MOCK_LOOKUP_OPTIONS_HASH
            )
            assert "data\\_version" not in lookup_pattern
            assert "policyengine\\_version=3.4.0" in lookup_pattern
            assert "runtime_app_name" not in lookup_pattern

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_completed_impact__uses_resolved_runtime_bundle_for_cache_lookup(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            mock_simulation_entrypoint.resolve_app_name.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_MODEL_VERSION,
                policyengine_version=MOCK_POLICYENGINE_VERSION,
            )

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_simulation_entrypoint",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_existing_impact__restores_stored_observability_id(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                completed_impact
            ]

            with (
                patch(
                    "policyengine_api.services.economy_service.restore_observability_id",
                    return_value=MOCK_OBSERVABILITY_ID,
                ) as restore_observability_id,
                patch(
                    "policyengine_api.services.economy_service.start_observability_id"
                ) as start_observability_id,
            ):
                result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            restore_observability_id.assert_called_once_with(MOCK_OBSERVABILITY_ID)
            start_observability_id.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_cached_impact_and_runtime_lookup_fails__returns_cached_result(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                completed_impact
            ]
            mock_simulation_entrypoint.resolve_app_name.side_effect = RuntimeError(
                "versions down"
            )

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert (
                result.data["policyengine_bundle"]["dataset"] == MOCK_RESOLVED_DATASET
            )
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_legacy_cached_impact_without_resolved_app_name__refreshes_cache(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            completed_impact = create_mock_reform_impact(
                status="ok",
                reform_impact_json=json.dumps(MOCK_REFORM_IMPACT_DATA),
                options_hash=MOCK_LOOKUP_OPTIONS_HASH,
            )
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            mock_simulation_entrypoint.resolve_app_name.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_MODEL_VERSION,
                policyengine_version=MOCK_POLICYENGINE_VERSION,
            )
            mock_simulation_entrypoint.run.assert_called_once()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_legacy_and_refreshed_cached_impacts__reuses_refreshed_entry(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            legacy_impact = create_mock_reform_impact(
                status="ok",
                reform_impact_json=json.dumps(MOCK_REFORM_IMPACT_DATA),
                options_hash=MOCK_LOOKUP_OPTIONS_HASH,
            )
            refreshed_impact = create_mock_reform_impact(status="ok")
            hash_prefix_lookup(mock_reform_impacts_service).side_effect = [
                [legacy_impact, refreshed_impact],
                [refreshed_impact],
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data["policyengine_bundle"] == {
                "model_version": MOCK_MODEL_VERSION,
                "policyengine_version": MOCK_POLICYENGINE_VERSION,
                "data_version": MOCK_DATA_VERSION,
                "dataset": MOCK_RESOLVED_DATASET,
            }
            assert hash_prefix_lookup(mock_reform_impacts_service).call_count == 2
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_legacy_cached_impact_and_lookup_fails__returns_cached_result(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            completed_impact = create_mock_reform_impact(
                status="ok",
                reform_impact_json=json.dumps(MOCK_REFORM_IMPACT_DATA),
                options_hash=MOCK_LOOKUP_OPTIONS_HASH,
            )
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                completed_impact
            ]
            mock_simulation_entrypoint.resolve_app_name.side_effect = RuntimeError(
                "versions down"
            )

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data["policyengine_bundle"]["model_version"] is None
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_legacy_computing_impact_without_app_name__then_reuses_execution(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            computing_impact = create_mock_reform_impact(
                status="computing",
                reform_impact_json=json.dumps({}),
            )
            hash_prefix_lookup(mock_reform_impacts_service).return_value = [
                computing_impact
            ]
            mock_simulation_entrypoint.get_execution_status.return_value = "running"

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            mock_simulation_entrypoint.resolve_app_name.assert_not_called()
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_simulation_entrypoint",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_exception__raises_error(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
        ):
            hash_prefix_lookup(mock_reform_impacts_service).side_effect = Exception(
                "Database error"
            )

            with pytest.raises(Exception, match="Database error") as exc_info:
                economy_service.get_economic_impact(**base_params)
            assert str(exc_info.value) == "Database error"

        @pytest.mark.usefixtures(
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_uk_request__preserves_model_version_in_bundle(
            self,
            economy_service,
            mock_country_package_versions,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_country_package_versions["uk"] = "2.7.8"
            hash_prefix_lookup(mock_reform_impacts_service).return_value = []

            economy_service.get_economic_impact(
                EconomicImpactRequest(
                    country_id="uk",
                    policy_id=MOCK_POLICY_ID,
                    baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                    region="uk",
                    dataset="default",
                    options=MOCK_OPTIONS,
                    api_version=MOCK_API_VERSION,
                    target="general",
                ),
                time_period=MOCK_TIME_PERIOD,
            )

            sim_params = mock_simulation_entrypoint.run.call_args[0][0]
            assert sim_params["_metadata"]["model_version"] == "2.7.8"

        @pytest.mark.usefixtures(
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
            "mock_reform_impacts_service",
        )
        def test__given_local_area_breakdown__submits_breakdown_to_simulation_api(
            self,
            economy_service,
            mock_country_package_versions,
            mock_simulation_entrypoint,
        ):
            mock_country_package_versions["uk"] = "2.7.8"

            result = economy_service.get_economic_impact(
                uk_breakdown_request(), time_period=MOCK_TIME_PERIOD
            )

            assert result.status == ImpactStatus.COMPUTING
            sim_params = mock_simulation_entrypoint.run.call_args.args[0]
            assert sim_params["breakdown"] == "local_areas"
            assert sim_params["country"] == "uk"
            assert sim_params["region"] == "uk"
            assert sim_params["include_cliffs"] is False

        @pytest.mark.usefixtures(
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        @pytest.mark.parametrize(
            "region", ["constituency/Aldershot", "country/france", "country/ "]
        )
        def test__given_invalid_breakdown__refuses_it_before_any_cache_read(
            self,
            economy_service,
            mock_country_package_versions,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
            region,
        ):
            mock_country_package_versions["uk"] = "2.7.8"

            with pytest.raises(ValueError, match="region uk or a UK country"):
                economy_service.get_economic_impact(
                    uk_breakdown_request(region=region), time_period=MOCK_TIME_PERIOD
                )

            assert mock_reform_impacts_service.mock_calls == []
            mock_simulation_entrypoint.resolve_app_name.assert_not_called()
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        @pytest.mark.parametrize("status_code", [400, 422])
        def test__given_simulation_api_refuses_breakdown__returns_error_without_storing(
            self,
            economy_service,
            mock_country_package_versions,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
            status_code,
        ):
            mock_country_package_versions["uk"] = "2.7.8"
            mock_simulation_entrypoint.run.side_effect = make_http_status_error(
                status_code,
                {"detail": "policyengine 6.7.5 does not support local-area breakdowns"},
            )

            result = economy_service.get_economic_impact(
                uk_breakdown_request(), time_period=MOCK_TIME_PERIOD
            )

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.message == (
                "The simulation API refused the local-area breakdown request "
                f"(HTTP {status_code}): "
                "policyengine 6.7.5 does not support local-area breakdowns"
            )
            # Nothing is stored, so a later request submits again once the
            # simulation API can run the breakdown.
            mock_reform_impacts_service.set_reform_impact.assert_not_called()
            mock_reform_impacts_service.set_error_reform_impact.assert_not_called()
            claim = mock_reform_impacts_service.claim_reform_impact_start
            mock_reform_impacts_service.release_reform_impact_start.assert_called_once_with(
                **claim.call_args.kwargs
            )

        @pytest.mark.usefixtures(
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
            "mock_reform_impacts_service",
        )
        def test__given_request_validation_errors_for_breakdown__names_each_field(
            self,
            economy_service,
            mock_country_package_versions,
            mock_simulation_entrypoint,
        ):
            mock_country_package_versions["uk"] = "2.7.8"
            mock_simulation_entrypoint.run.side_effect = make_http_status_error(
                422,
                {
                    "detail": [
                        {
                            "type": "extra_forbidden",
                            "loc": ["body", "breakdown"],
                            "msg": "Extra inputs are not permitted",
                            "input": "local_areas",
                        }
                    ]
                },
            )

            result = economy_service.get_economic_impact(
                uk_breakdown_request(), time_period=MOCK_TIME_PERIOD
            )

            assert result.status == ImpactStatus.ERROR
            assert result.message == (
                "The simulation API refused the local-area breakdown request "
                "(HTTP 422): body.breakdown: Extra inputs are not permitted"
            )

        @pytest.mark.usefixtures(
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        @pytest.mark.parametrize("status_code", [401, 403, 429, 500, 503])
        def test__given_other_simulation_api_failure_for_breakdown__raises(
            self,
            economy_service,
            mock_country_package_versions,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
            status_code,
        ):
            mock_country_package_versions["uk"] = "2.7.8"
            mock_simulation_entrypoint.run.side_effect = make_http_status_error(
                status_code, {"detail": "gateway unavailable"}
            )

            with pytest.raises(httpx.HTTPStatusError):
                economy_service.get_economic_impact(
                    uk_breakdown_request(), time_period=MOCK_TIME_PERIOD
                )

            mock_reform_impacts_service.release_reform_impact_start.assert_called_once()

        @pytest.mark.usefixtures(
            "mock_policyengine_version",
            "mock_policy_service",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_simulation_api_refuses_national_request__raises(
            self,
            economy_service,
            mock_country_package_versions,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
        ):
            mock_country_package_versions["uk"] = "2.7.8"
            mock_simulation_entrypoint.run.side_effect = make_http_status_error(
                400, {"detail": "invalid request"}
            )

            with pytest.raises(httpx.HTTPStatusError):
                economy_service.get_economic_impact(
                    replace(uk_breakdown_request(), options={}),
                    time_period=MOCK_TIME_PERIOD,
                )

            mock_reform_impacts_service.release_reform_impact_start.assert_called_once()

    class TestGetBudgetWindowEconomicImpact:
        @pytest.fixture
        def economy_service(
            self,
            mock_country_package_versions,
            mock_policy_service,
            mock_logger,
            mock_datetime,
            mock_submission_claim_id,
        ):
            return EconomyService()

        @pytest.fixture
        def base_params(self):
            return {
                "impact_request": EconomicImpactRequest(
                    country_id=MOCK_COUNTRY_ID,
                    policy_id=MOCK_POLICY_ID,
                    baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                    region=MOCK_REGION,
                    dataset=MOCK_DATASET,
                    options=MOCK_OPTIONS,
                    api_version=MOCK_API_VERSION,
                    target="general",
                ),
                "start_year": "2026",
                "window_size": 3,
            }

        def test__given_no_cached_batch__submits_parent_batch_and_returns_queued_result(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            batch_execution = create_mock_budget_window_batch_execution(
                batch_job_id="fc-budget-123",
                status="submitted",
            )
            mock_simulation_entrypoint.run_budget_window_batch.return_value = (
                batch_execution
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 0
            assert result.completed_years == []
            assert result.computing_years == []
            assert result.queued_years == ["2026", "2027", "2028"]
            assert result.cache_status == "miss"
            assert "Queued 2026" in result.message
            mock_simulation_entrypoint.run_budget_window_batch.assert_called_once()
            submitted_payload = (
                mock_simulation_entrypoint.run_budget_window_batch.call_args.args[0]
            )
            assert submitted_payload["start_year"] == "2026"
            assert submitted_payload["window_size"] == 3
            assert submitted_payload["max_parallel"] == 20
            assert submitted_payload["target"] == "general"
            assert "time_period" not in submitted_payload
            mock_budget_window_cache.claim_batch_start.assert_called_once_with(
                "budget-window-cache-key",
                MOCK_SUBMISSION_CLAIM_ID,
                MOCK_OBSERVABILITY_ID,
            )
            mock_budget_window_cache.store_submitted.assert_called_once_with(
                "budget-window-cache-key",
                "fc-budget-123",
                MOCK_OBSERVABILITY_ID,
            )
            mock_reform_impacts_service.set_reform_impact.assert_not_called()

        def test__given_completed_cached_result__returns_completed_batch_result(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            completed_result = complete_budget_window_result(
                annual_values={
                    "2026": {
                        "year": "2026",
                        "taxRevenueImpact": 100,
                        "federalTaxRevenueImpact": 80,
                        "stateTaxRevenueImpact": 20,
                        "benefitSpendingImpact": -10,
                        "budgetaryImpact": 90,
                    },
                },
                totals={
                    "year": "Total",
                    "taxRevenueImpact": 100,
                    "federalTaxRevenueImpact": 80,
                    "stateTaxRevenueImpact": 20,
                    "benefitSpendingImpact": -10,
                    "budgetaryImpact": 90,
                },
            )
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="completed",
                result=completed_result,
                observability_id=MOCK_OBSERVABILITY_ID,
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.progress == 100
            assert result.data == completed_result
            assert result.cache_status == "result-hit"
            mock_simulation_entrypoint.get_budget_window_batch_by_id.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_cached_batch_id__returns_running_batch_progress(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="running",
                    batch_progress=MockBatchProgress(
                        progress=33,
                        completed_years=["2026"],
                        running_years=["2027"],
                        queued_years=["2028"],
                    ),
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 33
            assert result.completed_years == ["2026"]
            assert result.computing_years == ["2027"]
            assert result.queued_years == ["2028"]
            assert result.cache_status == "batch-id-hit"
            assert "1 of 3 complete" in result.message
            mock_simulation_entrypoint.get_budget_window_batch_by_id.assert_called_once_with(
                "fc-budget-123"
            )

        def test__given_completed_batch_poll__caches_result_and_returns_completed(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            completed_result = complete_budget_window_result()
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="complete",
                    batch_progress=MockBatchProgress(
                        progress=100, completed_years=["2026", "2027", "2028"]
                    ),
                    result=completed_result,
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data == completed_result
            assert result.cache_status == "batch-id-hit"
            mock_budget_window_cache.set_completed_result.assert_called_once_with(
                "budget-window-cache-key",
                completed_result,
                MOCK_OBSERVABILITY_ID,
            )

        @pytest.mark.parametrize("malformed_result", [None, {}, []])
        def test__given_completed_batch_without_result__returns_error_without_caching(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
            malformed_result,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="complete",
                    batch_progress=MockBatchProgress(
                        progress=100,
                        completed_years=["2026", "2027"],
                        running_years=[],
                        queued_years=["2028"],
                    ),
                    result=malformed_result,
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.error == "Budget-window batch completed without a result"
            assert result.completed_years == ["2026", "2027"]
            assert result.computing_years == []
            assert result.queued_years == ["2028"]
            assert result.cache_status == "batch-id-hit"
            mock_budget_window_cache.set_completed_result.assert_not_called()
            mock_budget_window_cache.set_execution_failure.assert_called_once()

        def test__given_completed_batch_cache_write_fails__does_not_clear_batch_id(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            completed_result = complete_budget_window_result()
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_budget_window_cache.set_completed_result.return_value = False
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="complete",
                    batch_progress=MockBatchProgress(
                        progress=100, completed_years=["2026", "2027", "2028"]
                    ),
                    result=completed_result,
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data == completed_result
            mock_budget_window_cache.set_completed_result.assert_called_once_with(
                "budget-window-cache-key",
                completed_result,
                MOCK_OBSERVABILITY_ID,
            )

        def test__given_failed_batch_poll__returns_failed(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="failed",
                    batch_progress=MockBatchProgress(
                        progress=33,
                        completed_years=["2026"],
                        queued_years=["2028"],
                        failed_years=["2027"],
                    ),
                    error="Budget window failed for 2027",
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.error == "Budget window failed for 2027"
            assert result.completed_years == ["2026"]
            assert result.computing_years == []
            assert result.queued_years == ["2028"]
            assert result.cache_status == "batch-id-hit"
            mock_budget_window_cache.set_completed_result.assert_not_called()
            mock_budget_window_cache.set_execution_failure.assert_called_once()

        def test_typed_error_write_failure_retains_batch_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            error = SPMValidationError("SPM_YEAR_UNAVAILABLE", "No forecast for 2036")
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="expired-job",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_budget_window_cache.set_terminal_error.return_value = False
            mock_simulation_entrypoint.get_budget_window_batch_by_id.side_effect = error

            with pytest.raises(SPMValidationError) as raised:
                economy_service.get_budget_window_economic_impact(**base_params)

            assert raised.value is error
            mock_budget_window_cache.set_completed_result.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test_untyped_poll_error_keeps_existing_retry_behavior(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            error = make_http_status_error(422, payload={"detail": "Unknown error"})
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="existing-job",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.side_effect = error

            with pytest.raises(httpx.HTTPStatusError) as raised:
                economy_service.get_budget_window_economic_impact(**base_params)

            assert raised.value is error
            mock_budget_window_cache.set_terminal_error.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_existing_start_claim__does_not_submit_duplicate_batch(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            winning_observability_id = "00000000-0000-4000-8000-000000000099"
            mock_budget_window_cache.claim_batch_start.return_value = False
            mock_budget_window_cache.get_state.side_effect = [
                None,
                BudgetWindowCacheState(
                    status="starting",
                    submission_claim_id="winning-claim",
                    observability_id=winning_observability_id,
                ),
            ]

            with (
                patch(
                    "policyengine_api.services.economy_service.restore_observability_id",
                    return_value=winning_observability_id,
                ) as restore_observability_id,
                patch(
                    "policyengine_api.services.economy_service.start_observability_id"
                ) as start_observability_id,
            ):
                result = economy_service.get_budget_window_economic_impact(
                    **base_params
                )

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 0
            assert result.queued_years == ["2026", "2027", "2028"]
            assert result.cache_status == "starting-claim-hit"
            restore_observability_id.assert_called_with(winning_observability_id)
            start_observability_id.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_disappearing_start_claim__retries_before_binding_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            lifecycle_events = []
            claim_results = iter([False, True])
            mock_budget_window_cache.claim_batch_start.side_effect = lambda *_args: (
                lifecycle_events.append("claim") or next(claim_results)
            )
            mock_budget_window_cache.get_state.side_effect = [None, None]
            mock_simulation_entrypoint.run_budget_window_batch.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="submitted",
                )
            )

            with patch(
                "policyengine_api.services.economy_service.start_observability_id",
                side_effect=lambda value: lifecycle_events.append("bind") or value,
            ) as start_observability_id:
                result = economy_service.get_budget_window_economic_impact(
                    **base_params
                )

            assert result.status == ImpactStatus.COMPUTING
            assert result.cache_status == "miss"
            assert mock_budget_window_cache.claim_batch_start.call_count == 2
            assert mock_budget_window_cache.claim_batch_start.call_args_list == [
                call(
                    "budget-window-cache-key",
                    MOCK_SUBMISSION_CLAIM_ID,
                    MOCK_OBSERVABILITY_ID,
                ),
                call(
                    "budget-window-cache-key",
                    MOCK_SUBMISSION_CLAIM_ID,
                    MOCK_OBSERVABILITY_ID,
                ),
            ]
            start_observability_id.assert_called_once_with(MOCK_OBSERVABILITY_ID)
            assert lifecycle_events == ["claim", "claim", "bind"]
            mock_simulation_entrypoint.run_budget_window_batch.assert_called_once()

        def test__given_repeated_disappearing_claims__fails_without_binding_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.claim_batch_start.return_value = False
            mock_budget_window_cache.get_state.return_value = None

            with (
                patch(
                    "policyengine_api.services.economy_service.start_observability_id"
                ) as start_observability_id,
                pytest.raises(
                    CacheCoordinationError,
                    match="submission ownership changed repeatedly",
                ),
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

            assert mock_budget_window_cache.claim_batch_start.call_count == 3
            start_observability_id.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_cached_execution_failure__replays_failure_and_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            stored_observability_id = "00000000-0000-4000-8000-000000000099"
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="failed",
                observability_id=stored_observability_id,
                failure_type="execution",
                error={
                    "status": "error",
                    "error": "Budget window failed for 2027",
                    "completed_years": ["2026"],
                    "queued_years": ["2028"],
                },
            )

            with patch(
                "policyengine_api.services.economy_service.restore_observability_id",
                return_value=stored_observability_id,
            ) as restore_observability_id:
                result = economy_service.get_budget_window_economic_impact(
                    **base_params
                )

            assert result.status == ImpactStatus.ERROR
            assert result.error == "Budget window failed for 2027"
            assert result.cache_status == "failure-hit"
            restore_observability_id.assert_called_with(stored_observability_id)
            mock_simulation_entrypoint.get_budget_window_batch_by_id.assert_not_called()
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        def test__given_gateway_raises_before_returning_batch__clears_start_claim(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_simulation_entrypoint.run_budget_window_batch.side_effect = (
                RuntimeError("submit failed")
            )

            with pytest.raises(RuntimeError, match="submit failed"):
                economy_service.get_budget_window_economic_impact(**base_params)

            mock_budget_window_cache.clear_starting_claim.assert_called_once_with(
                "budget-window-cache-key",
                MOCK_SUBMISSION_CLAIM_ID,
                MOCK_OBSERVABILITY_ID,
            )

        @pytest.mark.parametrize("status_code", [400, 422])
        def test__given_modal_rejects_invalid_batch_submission__returns_failed_result(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
            status_code,
        ):
            rejection = make_http_status_error(
                status_code,
                {
                    "detail": (
                        "Invalid Hugging Face dataset URI: "
                        "'hf://policyengine/nonexistent-budget-window-test.h5@0.0.0'"
                    )
                },
            )
            mock_simulation_entrypoint.run_budget_window_batch.side_effect = rejection

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.error == (
                "Invalid Hugging Face dataset URI: "
                "'hf://policyengine/nonexistent-budget-window-test.h5@0.0.0'"
            )
            assert result.completed_years == []
            assert result.computing_years == []
            assert result.queued_years == ["2026", "2027", "2028"]
            assert result.cache_status == "miss"
            mock_budget_window_cache.clear_starting_claim.assert_not_called()
            mock_budget_window_cache.set_execution_failure.assert_called_once()

        @pytest.mark.parametrize("status_code", [401, 403, 429, 500])
        def test__given_modal_non_validation_error_on_batch_submission__raises(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
            status_code,
        ):
            mock_simulation_entrypoint.run_budget_window_batch.side_effect = (
                make_http_status_error(status_code, {"detail": "gateway unavailable"})
            )

            with pytest.raises(httpx.HTTPStatusError):
                economy_service.get_budget_window_economic_impact(**base_params)

            mock_budget_window_cache.clear_starting_claim.assert_called_once_with(
                "budget-window-cache-key",
                MOCK_SUBMISSION_CLAIM_ID,
                MOCK_OBSERVABILITY_ID,
            )
            mock_budget_window_cache.store_submitted.assert_not_called()

        @pytest.mark.parametrize(
            ("payload", "expected_message"),
            [
                ({"message": "gateway validation failed"}, "gateway validation failed"),
                ({"error": "invalid request"}, "invalid request"),
            ],
        )
        def test__given_modal_validation_json_error__extracts_message(
            self, economy_service, payload, expected_message
        ):
            error = make_http_status_error(400, payload)

            message = economy_service._build_submission_error_message(error)

            assert message == expected_message

        def test__given_modal_validation_error_list__names_each_field(
            self, economy_service
        ):
            error = make_http_status_error(
                422,
                {
                    "detail": [
                        {
                            "type": "missing",
                            "loc": ["body", "start_year"],
                            "msg": "Field required",
                            "input": {},
                        },
                        {
                            "type": "extra_forbidden",
                            "loc": ["body", "breakdown"],
                            "msg": "Extra inputs are not permitted",
                            "input": "local_areas",
                        },
                    ]
                },
            )

            message = economy_service._build_submission_error_message(error)

            assert message == (
                "body.start_year: Field required; "
                "body.breakdown: Extra inputs are not permitted"
            )

        def test__given_modal_rejects_batch_with_error_list__names_each_field(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_simulation_entrypoint.run_budget_window_batch.side_effect = (
                make_http_status_error(
                    422,
                    {
                        "detail": [
                            {
                                "type": "less_than_equal",
                                "loc": ["body", "window_size"],
                                "msg": "Input should be less than or equal to 75",
                                "input": 80,
                            }
                        ]
                    },
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.error == (
                "body.window_size: Input should be less than or equal to 75"
            )
            mock_budget_window_cache.set_execution_failure.assert_called_once()

        def test__given_modal_validation_plain_text_error__extracts_response_text(
            self, economy_service
        ):
            error = make_http_status_error(400, text="plain validation failed")

            message = economy_service._build_submission_error_message(error)

            assert message == "plain validation failed"

        def test__given_modal_validation_empty_error__falls_back_to_exception_text(
            self, economy_service
        ):
            error = make_http_status_error(400, text="")

            message = economy_service._build_submission_error_message(error)

            assert message == str(error)

        def test__given_cliff_target__raises_value_error(
            self, economy_service, base_params
        ):
            base_params["impact_request"] = replace(
                base_params["impact_request"], target="cliff"
            )

            with pytest.raises(
                ValueError,
                match="Budget-window calculations only support target='general'",
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        def test__given_oversized_window__raises_value_error(
            self, economy_service, base_params
        ):
            base_params["window_size"] = BUDGET_WINDOW_MAX_YEARS + 1

            with pytest.raises(
                ValueError,
                match=(f"window_size must be between 1 and {BUDGET_WINDOW_MAX_YEARS}"),
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        def test__given_end_year_after_2099__raises_value_error(
            self, economy_service, base_params
        ):
            base_params["start_year"] = "2090"
            base_params["window_size"] = 20

            with pytest.raises(
                ValueError,
                match=(
                    f"budget-window end_year must be {BUDGET_WINDOW_MAX_END_YEAR} "
                    "or earlier"
                ),
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        @pytest.mark.usefixtures(
            "mock_country_package_versions",
            "mock_simulation_entrypoint",
            "mock_logger",
            "mock_datetime",
            "mock_submission_claim_id",
        )
        def test__given_runtime_cache_version__uses_versioned_budget_window_cache_key(
            self,
            economy_service,
            base_params,
            mock_budget_window_cache,
            monkeypatch,
        ):
            cache_version = "e1cache01"

            monkeypatch.setattr(
                "policyengine_api.services.economy_service.get_economy_impact_cache_version",
                lambda _country_id, _api_version=None: cache_version,
            )
            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            cache_key_kwargs = mock_budget_window_cache.build_key.call_args.kwargs
            assert cache_key_kwargs["scope"].time_period == "budget_window:2026:3"
            assert cache_key_kwargs["api_version"] == cache_version

        def test__given_reordered_options__uses_same_budget_window_cache_identity(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="completed",
                result=complete_budget_window_result(),
                observability_id=MOCK_OBSERVABILITY_ID,
            )

            economy_service.get_budget_window_economic_impact(
                **{
                    **base_params,
                    "impact_request": replace(
                        base_params["impact_request"],
                        options={"staging_probe": "abc", "analysis_mode": "x"},
                    ),
                }
            )
            first_cache_key_kwargs = dict(
                mock_budget_window_cache.build_key.call_args.kwargs
            )
            mock_budget_window_cache.build_key.reset_mock()

            economy_service.get_budget_window_economic_impact(
                **{
                    **base_params,
                    "impact_request": replace(
                        base_params["impact_request"],
                        options={"analysis_mode": "x", "staging_probe": "abc"},
                    ),
                }
            )
            second_cache_key_kwargs = dict(
                mock_budget_window_cache.build_key.call_args.kwargs
            )

            assert first_cache_key_kwargs == second_cache_key_kwargs
            mock_simulation_entrypoint.run_budget_window_batch.assert_not_called()

        @pytest.mark.usefixtures(
            "mock_reform_impacts_service", "mock_simulation_entrypoint"
        )
        def test__given_legacy_us_region__normalizes_before_building_cache_key(
            self,
            economy_service,
            base_params,
            mock_budget_window_cache,
        ):
            base_params["impact_request"] = replace(
                base_params["impact_request"], region="ca", dataset="default"
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert mock_budget_window_cache.build_key.call_args.kwargs[
                "scope"
            ].region == ("state/ca")

        def test__given_unexpected_batch_status__raises_value_error(
            self,
            economy_service,
            base_params,
            mock_simulation_entrypoint,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_state.return_value = BudgetWindowCacheState(
                status="submitted",
                batch_job_id="fc-budget-123",
                observability_id=MOCK_OBSERVABILITY_ID,
            )
            mock_simulation_entrypoint.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="paused",
                )
            )

            with pytest.raises(
                ValueError,
                match="Unexpected budget-window batch execution state: paused",
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        def test__given_missing_progress__computes_progress_from_completed_years(
            self, economy_service
        ):
            result = economy_service._build_budget_window_computing_result(
                total_years=4,
                years=BudgetWindowYearProgress(
                    completed_years=["2026"],
                    computing_years=["2027", "2028", "2029"],
                    queued_years=[],
                ),
                progress=None,
            )

            assert result.progress == 25
            assert result.message == "Scoring 2027, 2028 + 1 more (1 of 4 complete)..."

        def test__given_no_active_or_queued_years__uses_generic_progress_message(
            self, economy_service
        ):
            result = economy_service._build_budget_window_computing_result(
                total_years=3,
                years=BudgetWindowYearProgress(
                    completed_years=["2026"],
                    computing_years=[],
                    queued_years=[],
                ),
                progress=None,
            )

            assert result.progress == 33
            assert result.message == "Scoring budget window (1 of 3 complete)..."

    class TestGetPreviousImpacts:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        def test_given_valid_parameters_calls_service_correctly(
            self, economy_service, mock_reform_impacts_service
        ):
            expected_impacts = [create_mock_reform_impact()]
            hash_prefix_lookup(
                mock_reform_impacts_service
            ).return_value = expected_impacts

            scope = ReformImpactScope(
                country_id=MOCK_COUNTRY_ID,
                reform_policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_DATASET,
                time_period=MOCK_TIME_PERIOD,
            )

            result = economy_service._get_previous_impacts(
                scope, options_hash=MOCK_OPTIONS_HASH, api_version=MOCK_API_VERSION
            )

            assert result == expected_impacts
            hash_prefix_lookup(mock_reform_impacts_service).assert_called_once_with(
                ReformImpactIdentity(
                    scope=scope,
                    api_version=MOCK_API_VERSION,
                    options_hash=MOCK_OPTIONS_HASH,
                ),
                economy_service._build_options_hash_lookup_pattern(MOCK_OPTIONS_HASH),
            )

    class TestGetMostRecentImpact:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.fixture
        def setup_options(self):
            return EconomicImpactSetupOptions(
                submission_claim_id=MOCK_SUBMISSION_CLAIM_ID,
                observability_id=MOCK_OBSERVABILITY_ID,
                country_id=MOCK_COUNTRY_ID,
                reform_policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_RESOLVED_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target="general",
                model_version=MOCK_MODEL_VERSION,
                policyengine_version=MOCK_POLICYENGINE_VERSION,
                data_version=MOCK_DATA_VERSION,
                options_hash=MOCK_OPTIONS_HASH,
            )

        def test__given_existing_impacts__returns_first_impact(
            self, economy_service, setup_options, mock_reform_impacts_service
        ):
            impacts = [
                create_mock_reform_impact(),
                create_mock_reform_impact(),
            ]
            hash_prefix_lookup(mock_reform_impacts_service).return_value = impacts

            result = economy_service._get_most_recent_impact(setup_options)

            assert result == impacts[0]

        def test__given_exact_and_prefix_matches__prefers_exact_options_hash(
            self, economy_service, setup_options, mock_reform_impacts_service
        ):
            impacts = [
                create_mock_reform_impact(options_hash=MOCK_LOOKUP_OPTIONS_HASH),
                create_mock_reform_impact(options_hash=MOCK_OPTIONS_HASH),
            ]
            hash_prefix_lookup(mock_reform_impacts_service).return_value = impacts

            result = economy_service._get_most_recent_impact(setup_options)

            assert result == impacts[1]

        def test__given_no_impacts__returns_none(
            self, economy_service, setup_options, mock_reform_impacts_service
        ):
            # Arrange
            hash_prefix_lookup(mock_reform_impacts_service).return_value = []

            # Act
            result = economy_service._get_most_recent_impact(setup_options)

            # Assert
            assert result is None

    class TestDetermineImpactAction:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        def test__given_no_impact__returns_create(self, economy_service):
            result = economy_service._determine_impact_action(None)

            assert result == ImpactAction.CREATE

        def test__given_ok_status__returns_completed(self, economy_service):
            impact = create_mock_reform_impact(status="ok")

            result = economy_service._determine_impact_action(impact)

            assert result == ImpactAction.COMPLETED

        def test__given_error_status__returns_failed(self, economy_service):
            impact = create_mock_reform_impact(status="error")

            result = economy_service._determine_impact_action(impact)

            assert result == ImpactAction.FAILED

        def test__given_computing_status__returns_computing(self, economy_service):
            impact = create_mock_reform_impact(status="computing")

            result = economy_service._determine_impact_action(impact)

            assert result == ImpactAction.COMPUTING

        def test__given_unknown_status__raises_error(self, economy_service):
            impact = create_mock_reform_impact(status="unknown")

            with pytest.raises(ValueError, match="Unknown impact status: unknown"):
                economy_service._determine_impact_action(impact)

    class TestHandleExecutionState:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.fixture
        def setup_options(self):
            return EconomicImpactSetupOptions(
                submission_claim_id=MOCK_SUBMISSION_CLAIM_ID,
                observability_id=MOCK_OBSERVABILITY_ID,
                country_id=MOCK_COUNTRY_ID,
                reform_policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_RESOLVED_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target="general",
                model_version=MOCK_MODEL_VERSION,
                policyengine_version=MOCK_POLICYENGINE_VERSION,
                data_version=MOCK_DATA_VERSION,
                options_hash=MOCK_OPTIONS_HASH,
            )

        def test_untyped_poll_error_does_not_persist_a_terminal_failure(
            self,
            economy_service,
            setup_options,
            mock_simulation_entrypoint,
            mock_reform_impacts_service,
        ):
            impact = create_mock_reform_impact(status="computing")
            error = make_http_status_error(422, payload={"detail": "Unknown error"})
            mock_simulation_entrypoint.get_execution_by_id.side_effect = error

            with pytest.raises(httpx.HTTPStatusError) as raised:
                economy_service._handle_computing_impact(setup_options, impact)

            assert raised.value is error
            mock_reform_impacts_service.set_error_reform_impact.assert_not_called()
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_succeeded_state__returns_completed_result(
            self,
            economy_service,
            setup_options,
            mock_simulation_entrypoint,
            mock_reform_impacts_service,
        ):
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_simulation_entrypoint.get_execution_result.return_value = (
                MOCK_REFORM_IMPACT_DATA
            )

            result = economy_service._handle_execution_state(
                setup_options, "complete", reform_impact, mock_execution
            )

            assert result.status == ImpactStatus.OK
            assert result.data["policyengine_bundle"] == {
                "model_version": MOCK_MODEL_VERSION,
                "policyengine_version": MOCK_POLICYENGINE_VERSION,
                "data_version": MOCK_DATA_VERSION,
                "dataset": MOCK_RESOLVED_DATASET,
            }
            mock_reform_impacts_service.set_complete_reform_impact.assert_called_once()
            write_values = (
                mock_reform_impacts_service.set_complete_reform_impact.call_args.kwargs
            )
            assert isinstance(write_values["reform_impact_json"], dict)
            assert (
                write_values["reform_impact_json"]["poverty_impact"]
                == (MOCK_REFORM_IMPACT_DATA["poverty_impact"])
            )

        @pytest.mark.usefixtures("mock_logger")
        def test__given_failed_state__returns_error_result(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            result = economy_service._handle_execution_state(
                setup_options, "failed", reform_impact
            )

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.message == "Simulation entrypoint execution failed"
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_active_state__returns_computing_result(
            self, economy_service, setup_options
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact
            )

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        def test__given_unknown_state__raises_error(
            self, economy_service, setup_options
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            with pytest.raises(
                ValueError, match="Unexpected sim API execution state: UNKNOWN"
            ):
                economy_service._handle_execution_state(
                    setup_options, "UNKNOWN", reform_impact
                )

        # Modal status tests
        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_complete_state__then_returns_completed_result(
            self,
            economy_service,
            setup_options,
            mock_simulation_entrypoint,
            mock_reform_impacts_service,
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_simulation_entrypoint.get_execution_result.return_value = (
                MOCK_REFORM_IMPACT_DATA
            )

            # When
            result = economy_service._handle_execution_state(
                setup_options, "complete", reform_impact, mock_execution
            )

            # Then
            assert result.status == ImpactStatus.OK
            assert result.data["policyengine_bundle"] == {
                "model_version": MOCK_MODEL_VERSION,
                "policyengine_version": MOCK_POLICYENGINE_VERSION,
                "data_version": MOCK_DATA_VERSION,
                "dataset": MOCK_RESOLVED_DATASET,
            }
            mock_reform_impacts_service.set_complete_reform_impact.assert_called_once()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_failed_state__then_returns_error_result(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_execution.error = None

            # When
            result = economy_service._handle_execution_state(
                setup_options, "failed", reform_impact, mock_execution
            )

            # Then
            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_failure_with_error_message__includes_error_in_message(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_execution.error = "Simulation timed out"

            # When
            result = economy_service._handle_execution_state(
                setup_options, "failed", reform_impact, mock_execution
            )

            # Then
            assert result.status == ImpactStatus.ERROR
            # Verify the error message was passed to the service
            call_args = mock_reform_impacts_service.set_error_reform_impact.call_args
            assert "Simulation timed out" in call_args[1]["message"]

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_running_state__then_returns_computing_result(
            self, economy_service, setup_options
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")

            # When
            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact
            )

            # Then
            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_running_state_with_run_progress__then_relays_it(
            self, economy_service, setup_options
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            execution = ModalSimulationExecution(
                job_id="fc-job-1",
                status="running",
                run_progress=SimulationRunProgress(
                    stage="reform", progress=67, progress_max=96
                ),
            )

            # When
            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact, execution
            )

            # Then
            assert result.status == ImpactStatus.COMPUTING
            assert result.run_progress.to_dict() == {
                "stage": "reform",
                "progress": 67,
                "progress_max": 96,
            }
            assert "run_progress" not in result.to_dict()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_running_state_without_run_progress__then_has_none(
            self, economy_service, setup_options
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            execution = ModalSimulationExecution(job_id="fc-job-1", status="running")

            # When
            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact, execution
            )

            # Then
            assert result.status == ImpactStatus.COMPUTING
            assert result.run_progress is None

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_submitted_state__then_returns_computing_result(
            self, economy_service, setup_options
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")

            # When
            result = economy_service._handle_execution_state(
                setup_options, "submitted", reform_impact
            )

            # Then
            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

    class TestCreateSubmissionClaimId:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        def test_returns_uuid_string(self, economy_service, mock_submission_claim_id):
            result = economy_service._create_submission_claim_id()

            assert result == MOCK_SUBMISSION_CLAIM_ID
            mock_submission_claim_id.assert_called_once_with()


class TestEconomicImpactResult:
    class TestToDict:
        def test__given_completed_result__returns_correct_dict(self):
            result = EconomicImpactResult.completed(MOCK_REFORM_IMPACT_DATA)

            result_dict = result.to_dict()

            assert result_dict == {
                "status": "ok",
                "data": MOCK_REFORM_IMPACT_DATA,
                "message": None,
            }

        def test__given_computing_result__returns_correct_dict(self):
            result = EconomicImpactResult.computing()

            result_dict = result.to_dict()

            assert result_dict == {
                "status": "computing",
                "data": None,
                "message": None,
            }

        def test__given_error_result__returns_correct_dict(self):
            with patch("policyengine_api.services.economy_service.logger"):
                result = EconomicImpactResult.error("Test error message")

            result_dict = result.to_dict()

            assert result_dict == {
                "status": "error",
                "data": None,
                "message": "Test error message",
            }

    class TestClassMethods:
        def test__given_completed__creates_correct_instance(self):
            result = EconomicImpactResult.completed(MOCK_REFORM_IMPACT_DATA)

            assert result.status == ImpactStatus.OK
            assert result.data == MOCK_REFORM_IMPACT_DATA

        def test__given_computing__creates_correct_instance(self):
            result = EconomicImpactResult.computing()

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        def test__given_error__creates_correct_instance_and_logs(self):
            with patch(
                "policyengine_api.services.economy_service.logger"
            ) as mock_logger:
                result = EconomicImpactResult.error("Test error message")

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.message == "Test error message"
            mock_logger.log_struct.assert_called_once()


class TestEconomicImpactSetupOptions:
    def test__given_valid_data__creates_instance(self):
        options = EconomicImpactSetupOptions(
            submission_claim_id=MOCK_SUBMISSION_CLAIM_ID,
            observability_id=MOCK_OBSERVABILITY_ID,
            country_id=MOCK_COUNTRY_ID,
            reform_policy_id=MOCK_POLICY_ID,
            baseline_policy_id=MOCK_BASELINE_POLICY_ID,
            region=MOCK_REGION,
            dataset=MOCK_DATASET,
            time_period=MOCK_TIME_PERIOD,
            options=MOCK_OPTIONS,
            api_version=MOCK_API_VERSION,
            target="general",
            options_hash=MOCK_OPTIONS_HASH,
        )

        assert options.submission_claim_id == MOCK_SUBMISSION_CLAIM_ID
        assert options.country_id == MOCK_COUNTRY_ID
        assert options.reform_policy_id == MOCK_POLICY_ID
        assert options.baseline_policy_id == MOCK_BASELINE_POLICY_ID
        assert options.region == MOCK_REGION
        assert options.dataset == MOCK_DATASET
        assert options.time_period == MOCK_TIME_PERIOD
        assert options.options == MOCK_OPTIONS
        assert options.api_version == MOCK_API_VERSION
        assert options.target == "general"
        assert options.options_hash == MOCK_OPTIONS_HASH

    class TestSetupSimOptions:
        """Tests for _setup_sim_options method.

        Note: _setup_sim_options now expects pre-normalized regions and returns
        no concrete data field for default datasets. The simulation gateway
        resolves the certified dataset from the requested .py bundle.
        """

        test_country_id = "us"
        test_reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
        test_current_law_baseline_policy = json.dumps({})
        test_region = "us"
        test_time_period = 2025
        test_scope: Literal["macro"] = "macro"

        def test__given_us_nationwide__returns_correct_sim_options(self):
            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                setup_options_for(self.test_country_id, self.test_region),
                reform_policy=self.test_reform_policy,
                baseline_policy=self.test_current_law_baseline_policy,
                time_period=self.test_time_period,
            )

            sim_options = sim_options_model.model_dump()

            assert sim_options["country"] == self.test_country_id
            assert sim_options["scope"] == self.test_scope
            assert sim_options["reform"] == json.loads(self.test_reform_policy)
            assert sim_options["baseline"] == json.loads(
                self.test_current_law_baseline_policy
            )
            assert sim_options["time_period"] == self.test_time_period
            assert sim_options["region"] == "us"
            assert "data" not in sim_options

        def test__given_us_state_ca__returns_correct_sim_options(self):
            # Test with a normalized US state (prefixed format)
            country_id = "us"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "state/ca"  # Pre-normalized
            time_period = 2025
            scope = "macro"

            service = EconomyService()
            sim_options_model = service._setup_sim_options(
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
            )
            sim_options = sim_options_model.model_dump()

            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ca"
            assert "data" not in sim_options

        def test__given_us_state_utah__returns_correct_sim_options(self):
            # Test with normalized Utah state
            country_id = "us"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "state/ut"  # Pre-normalized
            time_period = 2025
            scope = "macro"

            service = EconomyService()
            sim_options_model = service._setup_sim_options(
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
            )
            sim_options = sim_options_model.model_dump()

            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ut"
            assert "data" not in sim_options

        def test__given_cliff_target__returns_correct_sim_options(self):
            country_id = "us"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "us"
            time_period = 2025
            scope = "macro"

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
                include_cliffs=True,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == region
            assert "data" not in sim_options
            assert sim_options["include_cliffs"] is True

        def test__given_uk__returns_correct_sim_options(self):
            country_id = "uk"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "uk"
            time_period = 2025

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["country"] == country_id
            assert sim_options["region"] == region
            assert "data" not in sim_options

        def test__given_congressional_district__returns_correct_sim_options(
            self,
        ):
            country_id = "us"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "congressional_district/CA-37"  # Pre-normalized
            time_period = 2025

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["region"] == "congressional_district/CA-37"
            assert "data" not in sim_options

        def test__given_local_area_breakdown__sends_breakdown(self):
            setup_options = setup_options_for("uk", "country/scotland")
            setup_options.options = {"breakdown": "local_areas"}

            sim_options = (
                EconomyService()
                ._setup_sim_options(
                    setup_options,
                    reform_policy=self.test_reform_policy,
                    baseline_policy=self.test_current_law_baseline_policy,
                    time_period=2026,
                )
                .model_dump(mode="json")
            )

            assert sim_options["breakdown"] == "local_areas"
            assert sim_options["region"] == "country/scotland"

        @pytest.mark.parametrize("mode", ["python", "json"])
        def test__given_no_breakdown__sends_no_breakdown_field(self, mode):
            sim_options = (
                EconomyService()
                ._setup_sim_options(
                    setup_options_for("uk", "uk"),
                    reform_policy=self.test_reform_policy,
                    baseline_policy=self.test_current_law_baseline_policy,
                    time_period=2026,
                )
                .model_dump(mode=mode)
            )

            assert "breakdown" not in sim_options

        def test__given_uk_northern_ireland__sends_registry_code_but_keeps_scope(
            self,
        ):
            setup_options = setup_options_for("uk", "country/ni")

            sim_options = EconomyService()._setup_sim_options(
                setup_options,
                reform_policy=self.test_reform_policy,
                baseline_policy=self.test_current_law_baseline_policy,
                time_period=2026,
            )

            assert sim_options.region == "country/northern_ireland"
            # The cache scope keeps the public region name.
            assert setup_options.region == "country/ni"

    class TestSetupRegion:
        """Tests for _setup_region method.

        Note: _setup_region now only validates regions - it assumes normalization
        has already been done by normalize_us_region() earlier in the flow.
        """

        def test__given_prefixed_us_state__returns_unchanged(self):
            # Test with a normalized US state (prefixed format)
            service = EconomyService()
            result = service._setup_region("us", "state/ca")
            assert result == "state/ca"

        def test__given_non_us_region__returns_unchanged(self):
            # Test with non-US region - no validation performed
            service = EconomyService()
            result = service._setup_region("uk", "country/england")
            assert result == "country/england"

        def test__given_us_national__returns_us(self):
            service = EconomyService()
            result = service._setup_region("us", "us")
            assert result == "us"

        def test__given_uk_northern_ireland__returns_the_region_registry_code(self):
            # API v1's metadata publishes country/ni; .py's UK region registry
            # names the region country/northern_ireland.
            service = EconomyService()
            result = service._setup_region("uk", "country/ni")
            assert result == "country/northern_ireland"

        @pytest.mark.parametrize(
            "region",
            [
                "uk",
                "country/england",
                "country/scotland",
                "country/wales",
                "country/northern_ireland",
                "constituency/Aldershot",
            ],
        )
        def test__given_other_uk_region__returns_unchanged(self, region):
            assert EconomyService()._setup_region("uk", region) == region

        def test__given_prefixed_state_tx__returns_unchanged(self):
            service = EconomyService()
            result = service._setup_region("us", "state/tx")
            assert result == "state/tx"

        def test__given_congressional_district__returns_unchanged(self):
            service = EconomyService()
            result = service._setup_region("us", "congressional_district/CA-37")
            assert result == "congressional_district/CA-37"

        def test__given_lowercase_congressional_district__returns_unchanged(
            self,
        ):
            service = EconomyService()
            result = service._setup_region("us", "congressional_district/ca-37")
            assert result == "congressional_district/ca-37"

        def test__given_invalid_prefixed_state__raises_value_error(self):
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid US state: 'mb'"):
                service._setup_region("us", "state/mb")

        def test__given_invalid_congressional_district__raises_value_error(
            self,
        ):
            service = EconomyService()
            with pytest.raises(
                ValueError, match="Invalid congressional district: 'cruft'"
            ):
                service._setup_region("us", "congressional_district/cruft")

        def test__given_invalid_prefix__raises_value_error(self):
            service = EconomyService()
            with pytest.raises(
                ValueError, match="Invalid US region: 'invalid_prefix/tx'"
            ):
                service._setup_region("us", "invalid_prefix/tx")

        def test__given_invalid_bare_value__raises_value_error(self):
            # Bare values without prefix are now invalid (should be normalized first)
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid US region: 'invalid_value'"):
                service._setup_region("us", "invalid_value")

        def test__given_place_region__returns_unchanged(self):
            # Test normalized "place/STATE-FIPS" format passes through
            service = EconomyService()
            result = service._setup_region("us", "place/NJ-57000")
            assert result == "place/NJ-57000"

        def test__given_invalid_place_format__raises_value_error(self):
            # Test place without hyphen raises error
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid place format"):
                service._setup_region("us", "place/invalid")

        def test__given_invalid_place_state__raises_value_error(self):
            # Test place with invalid state code raises error
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid state in place code"):
                service._setup_region("us", "place/XX-57000")

        def test__given_invalid_place_fips__raises_value_error(self):
            # Test place with invalid FIPS code raises error
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid FIPS code"):
                service._setup_region("us", "place/NJ-abc")

    class TestDatasetSelection:
        @pytest.mark.parametrize(
            "dataset",
            ["populace_us_2024", "enhanced_cps", "hf://example/data.h5"],
        )
        def test__given_custom_dataset__rejects_it(self, dataset):
            service = EconomyService()
            with pytest.raises(ValueError, match="Custom datasets are not supported"):
                service._build_economic_impact_setup_options(
                    EconomicImpactRequest(
                        country_id="us",
                        policy_id=MOCK_POLICY_ID,
                        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                        region="us",
                        dataset=dataset,
                        options={},
                        api_version=MOCK_API_VERSION,
                    ),
                    time_period=MOCK_TIME_PERIOD,
                )

    class TestLocalAreaBreakdownSelection:
        @pytest.mark.parametrize(
            "region",
            [
                "uk",
                "country/england",
                "country/scotland",
                "country/wales",
                "country/ni",
                "country/northern_ireland",
            ],
        )
        def test__given_uk_or_uk_country__accepts_breakdown(self, region):
            gateway = MagicMock()

            setup_options = EconomyService(
                simulation_entrypoint_=gateway
            )._build_economic_impact_setup_options(
                uk_breakdown_request(region=region), time_period=MOCK_TIME_PERIOD
            )

            assert setup_options.options == {"breakdown": "local_areas"}
            assert setup_options.region == region
            assert setup_options.options_hash.startswith(
                "[breakdown=local_areas&dataset=default&"
            )

        @pytest.mark.parametrize(
            ("country_id", "region", "target", "message"),
            [
                ("us", "us", "general", "only available for UK"),
                ("us", "state/ca", "general", "only available for UK"),
                (
                    "uk",
                    "constituency/Aldershot",
                    "general",
                    "region uk or a UK country",
                ),
                (
                    "uk",
                    "local_authority/E07000092",
                    "general",
                    "region uk or a UK country",
                ),
                ("uk", "scotland", "general", "region uk or a UK country"),
                ("uk", "country/", "general", "region uk or a UK country"),
                # A query value of country/%20 reaches the service decoded.
                ("uk", "country/ ", "general", "region uk or a UK country"),
                ("uk", "country/%20", "general", "region uk or a UK country"),
                ("uk", "country/NI", "general", "region uk or a UK country"),
                ("uk", "country/france", "general", "region uk or a UK country"),
                ("uk", "Country/scotland", "general", "region uk or a UK country"),
                ("uk", "country/scotland ", "general", "region uk or a UK country"),
                ("uk", "UK", "general", "region uk or a UK country"),
                ("uk", " uk", "general", "region uk or a UK country"),
                ("uk", "uk", "cliff", "target=cliff"),
                ("uk", "country/wales", "cliff", "target=cliff"),
            ],
        )
        def test__given_unsupported_request__rejects_breakdown(
            self, country_id, region, target, message
        ):
            gateway = MagicMock()

            with pytest.raises(ValueError, match=message):
                EconomyService(
                    simulation_entrypoint_=gateway
                )._build_economic_impact_setup_options(
                    uk_breakdown_request(
                        country_id=country_id, region=region, target=target
                    ),
                    time_period=MOCK_TIME_PERIOD,
                )

            # Rejected before the worker's SPM capability is fetched.
            gateway.get_spm_capability.assert_not_called()

        def test__given_unknown_breakdown_option__rejects_it(self):
            request = replace(
                uk_breakdown_request(), options={"breakdown": "constituencies"}
            )

            with pytest.raises(ValueError, match="Unknown breakdown: 'constituencies'"):
                EconomyService(
                    simulation_entrypoint_=MagicMock()
                )._build_economic_impact_setup_options(
                    request, time_period=MOCK_TIME_PERIOD
                )

    class TestValidateUsRegion:
        """Tests for the _validate_us_region method."""

        def test__given_valid_state__does_not_raise(self):
            service = EconomyService()
            # Should not raise
            service._validate_us_region("state/ca")

        def test__given_valid_state_uppercase__does_not_raise(self):
            service = EconomyService()
            # Case-insensitive validation
            service._validate_us_region("state/CA")

        def test__given_invalid_state__raises_value_error(self):
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid US state: 'mb'"):
                service._validate_us_region("state/mb")

        def test__given_valid_congressional_district__does_not_raise(self):
            service = EconomyService()
            service._validate_us_region("congressional_district/CA-37")

        def test__given_valid_congressional_district_lowercase__does_not_raise(
            self,
        ):
            service = EconomyService()
            service._validate_us_region("congressional_district/ca-37")

        def test__given_invalid_congressional_district__raises_value_error(
            self,
        ):
            service = EconomyService()
            with pytest.raises(
                ValueError, match="Invalid congressional district: 'CA-99'"
            ):
                service._validate_us_region("congressional_district/CA-99")

        def test__given_nonexistent_district__raises_value_error(self):
            service = EconomyService()
            with pytest.raises(
                ValueError, match="Invalid congressional district: 'cruft'"
            ):
                service._validate_us_region("congressional_district/cruft")


class TestBuildOptionsHash:
    def test__given_reordered_options__returns_same_hash(self):
        service = EconomyService()

        bundle = RuntimeBundleIdentity(
            dataset="hf://policyengine/test.h5@1.0", model_version="1.2.3"
        )

        first = service._build_options_hash(
            options={"staging_probe": "abc", "analysis_mode": "x"}, bundle=bundle
        )
        second = service._build_options_hash(
            options={"analysis_mode": "x", "staging_probe": "abc"}, bundle=bundle
        )

        assert first == second
