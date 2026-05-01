import datetime
import json
import sys
import pytest
from unittest.mock import patch, MagicMock
from typing import Literal
from types import ModuleType

try:
    from policyengine.simulation import SimulationOptions  # noqa: F401
except ModuleNotFoundError:
    policyengine_module = sys.modules.setdefault(
        "policyengine", ModuleType("policyengine")
    )
    simulation_module = ModuleType("policyengine.simulation")
    utils_module = ModuleType("policyengine.utils")
    data_module = ModuleType("policyengine.utils.data")
    datasets_module = ModuleType("policyengine.utils.data.datasets")

    class _StubSimulationOptions:
        def __init__(self, payload):
            self._payload = payload

        @classmethod
        def model_validate(cls, payload):
            return cls(payload)

        def model_dump(self):
            return dict(self._payload)

    simulation_module.SimulationOptions = _StubSimulationOptions
    policyengine_module.simulation = simulation_module

    def _stub_get_default_dataset(country, region):
        if country == "us":
            if region == "us":
                return "gs://policyengine-us-data/enhanced_cps_2024.h5"
            if region == "state/ca":
                return "gs://policyengine-us-data/states/CA.h5"
            if region == "state/ut":
                return "gs://policyengine-us-data/states/UT.h5"
            if region == "place/NJ-57000":
                return "gs://policyengine-us-data/states/NJ.h5"
            if region == "congressional_district/CA-37":
                return "gs://policyengine-us-data/districts/CA-37.h5"
        if country == "uk" and region == "uk":
            return "gs://policyengine-uk-data-private/enhanced_frs_2023_24.h5"
        raise ValueError(
            f"Error getting default dataset for country={country}, region={region}: unsupported in test stub"
        )

    datasets_module.get_default_dataset = _stub_get_default_dataset
    data_module.datasets = datasets_module
    utils_module.data = data_module
    policyengine_module.utils = utils_module
    sys.modules["policyengine.simulation"] = simulation_module
    sys.modules["policyengine.utils"] = utils_module
    sys.modules["policyengine.utils.data"] = data_module
    sys.modules["policyengine.utils.data.datasets"] = datasets_module

from policyengine_api.services.economy_service import (
    BUDGET_WINDOW_MAX_END_YEAR,
    BUDGET_WINDOW_MAX_YEARS,
    EconomyService,
    EconomicImpactResult,
    EconomicImpactSetupOptions,
    ImpactAction,
    ImpactStatus,
    PENDING_EXECUTION_ID_PREFIX,
    PROVISIONAL_CLAIM_TTL_SECONDS,
    STALE_PROVISIONAL_IMPACT_MESSAGE,
)
from tests.fixtures.services.economy_service import (
    MOCK_COUNTRY_ID,
    MOCK_DATA_VERSION,
    MOCK_POLICY_ID,
    MOCK_BASELINE_POLICY_ID,
    MOCK_REGION,
    MOCK_DATASET,
    MOCK_TIME_PERIOD,
    MOCK_API_VERSION,
    MOCK_MODEL_VERSION,
    MOCK_POLICYENGINE_VERSION,
    MOCK_OPTIONS,
    MOCK_LOOKUP_OPTIONS_HASH,
    MOCK_OPTIONS_HASH,
    MOCK_EXECUTION_ID,
    MOCK_PROCESS_ID,
    MOCK_RUN_ID,
    MOCK_REFORM_IMPACT_DATA,
    MOCK_RESOLVED_DATASET,
    MOCK_RESOLVED_APP_NAME,
    create_mock_budget_window_batch_execution,
    create_mock_reform_impact,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)


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


class TestEconomyService:
    class TestGetEconomicImpact:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.fixture
        def base_params(self):
            return {
                "country_id": MOCK_COUNTRY_ID,
                "policy_id": MOCK_POLICY_ID,
                "baseline_policy_id": MOCK_BASELINE_POLICY_ID,
                "region": MOCK_REGION,
                "dataset": MOCK_DATASET,
                "time_period": MOCK_TIME_PERIOD,
                "options": MOCK_OPTIONS,
                "api_version": MOCK_API_VERSION,
                "target": "general",
            }

        def test__given_completed_impact__returns_completed_result(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
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
            (
                mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.assert_called_once()
            )
            mock_simulation_api.run.assert_not_called()

        def test__given_legacy_completed_impact__refreshes_cache(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            completed_impact = create_mock_reform_impact(
                status="ok",
                reform_impact_json=json.dumps(MOCK_REFORM_IMPACT_DATA),
                options_hash=MOCK_LOOKUP_OPTIONS_HASH,
            )
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            mock_simulation_api.resolve_app_name.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_MODEL_VERSION,
            )
            mock_simulation_api.run.assert_called_once()

        def test__given_error_impact__returns_error_result(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            error_impact = create_mock_reform_impact(
                status="error",
                reform_impact_json=json.dumps({}),
            )
            error_impact["message"] = "Failed to start simulation API job"
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                error_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.message == "Failed to start simulation API job"
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.assert_called_once()
            mock_simulation_api.run.assert_not_called()

        def test__given_computing_impact_with_succeeded_execution__returns_completed_result(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            computing_impact = create_mock_reform_impact(status="computing")
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                computing_impact
            ]
            mock_simulation_api.get_execution_status.return_value = "complete"
            mock_simulation_api.get_execution_result.return_value = (
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
            mock_simulation_api.get_execution_by_id.assert_called_once_with(
                MOCK_EXECUTION_ID
            )
            mock_reform_impacts_service.set_complete_reform_impact.assert_called_once()

        def test__given_computing_impact_with_failed_execution__returns_error_result(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            computing_impact = create_mock_reform_impact(status="computing")
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                computing_impact
            ]
            mock_simulation_api.get_execution_status.return_value = "failed"

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        def test__given_computing_impact_with_active_execution__returns_computing_result(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            computing_impact = create_mock_reform_impact(status="computing")
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                computing_impact
            ]
            mock_simulation_api.get_execution_status.return_value = "running"

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        def test__given_no_previous_impact__creates_new_simulation(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = []

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None
            mock_simulation_api.run.assert_called_once()
            mock_reform_impacts_service.set_reform_impact.assert_called_once()
            assert any(
                call.args == (datetime.timezone.utc,)
                for call in mock_datetime.now.call_args_list
            )
            mock_reform_impacts_service.update_reform_impact_execution_id.assert_called_once_with(
                country_id=MOCK_COUNTRY_ID,
                policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_RESOLVED_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options_hash=MOCK_OPTIONS_HASH,
                current_execution_id=f"{PENDING_EXECUTION_ID_PREFIX}{MOCK_PROCESS_ID}",
                new_execution_id=MOCK_EXECUTION_ID,
            )

        def test__given_no_previous_impact__includes_metadata_in_simulation_params(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            """Verify that _metadata with policy IDs is passed to simulation API."""
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = []

            economy_service.get_economic_impact(**base_params)

            # Get the params passed to simulation_api.run()
            call_args = mock_simulation_api.run.call_args
            sim_params = call_args[0][0]  # First positional argument

            # Verify _metadata is included with correct values
            assert "_metadata" in sim_params
            assert sim_params["_metadata"]["reform_policy_id"] == MOCK_POLICY_ID
            assert (
                sim_params["_metadata"]["baseline_policy_id"] == MOCK_BASELINE_POLICY_ID
            )
            assert sim_params["_metadata"]["process_id"] == MOCK_PROCESS_ID
            assert sim_params["_metadata"]["model_version"] == MOCK_MODEL_VERSION
            assert sim_params["_metadata"]["policyengine_version"] is None
            assert sim_params["_metadata"]["data_version"] == MOCK_DATA_VERSION
            assert sim_params["_metadata"]["dataset"] == MOCK_RESOLVED_DATASET
            assert (
                sim_params["_metadata"]["resolved_app_name"] == MOCK_RESOLVED_APP_NAME
            )

        def test__given_no_previous_impact__includes_telemetry_in_simulation_params(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            mock_reform_impacts_service.get_all_reform_impacts.return_value = []

            economy_service.get_economic_impact(**base_params)

            sim_params = mock_simulation_api.run.call_args[0][0]

            assert sim_params["_telemetry"]["run_id"]
            assert sim_params["_telemetry"]["process_id"] == MOCK_PROCESS_ID
            assert sim_params["_telemetry"]["simulation_kind"] == "national"
            assert sim_params["_telemetry"]["geography_type"] == "national"
            assert sim_params["_telemetry"]["geography_code"] == MOCK_COUNTRY_ID
            assert sim_params["_telemetry"]["capture_mode"] == "disabled"
            assert sim_params["_telemetry"]["config_hash"].startswith("sha256:")
            progress_log = mock_logger.log_struct.call_args_list[-1].args[0]
            assert progress_log["run_id"] == MOCK_RUN_ID
            assert (
                mock_logger.log_struct.call_args_list[-1].kwargs["severity"] == "INFO"
            )

        def test__given_simulation_api_submission_failure__marks_provisional_claim_error(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            mock_reform_impacts_service.get_all_reform_impacts.return_value = []
            mock_simulation_api.run.side_effect = RuntimeError("gateway unavailable")

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert (
                result.message
                == "Failed to start simulation API job: gateway unavailable"
            )
            mock_reform_impacts_service.set_reform_impact.assert_called_once()
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once_with(
                country_id=MOCK_COUNTRY_ID,
                policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_RESOLVED_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options_hash=MOCK_OPTIONS_HASH,
                message="Failed to start simulation API job: gateway unavailable",
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}{MOCK_PROCESS_ID}",
            )
            mock_reform_impacts_service.update_reform_impact_execution_id.assert_not_called()

        def test__given_simulation_setup_failure__marks_provisional_claim_error(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            mock_reform_impacts_service.get_all_reform_impacts.return_value = []
            with patch.object(
                economy_service,
                "_setup_sim_options",
                side_effect=ValueError("Invalid US state: 'zz'"),
            ):
                result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert (
                result.message
                == "Failed to start simulation API job: Invalid US state: 'zz'"
            )
            mock_reform_impacts_service.set_reform_impact.assert_called_once()
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once_with(
                country_id=MOCK_COUNTRY_ID,
                policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_RESOLVED_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options_hash=MOCK_OPTIONS_HASH,
                message="Failed to start simulation API job: Invalid US state: 'zz'",
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}{MOCK_PROCESS_ID}",
            )
            mock_simulation_api.run.assert_not_called()
            mock_reform_impacts_service.update_reform_impact_execution_id.assert_not_called()

        def test__given_claim_lock_timeout_and_existing_provisional_claim__returns_computing(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_numpy_random,
        ):
            provisional_impact = create_mock_reform_impact(
                status="computing",
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}job_other",
                start_time=datetime.datetime.now(datetime.timezone.utc),
            )
            mock_reform_impacts_service.get_all_reform_impacts.side_effect = [
                [],
                [provisional_impact],
            ]
            mock_reform_impacts_service.claim_lock.side_effect = TimeoutError(
                "lock busy"
            )

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            mock_simulation_api.run.assert_not_called()

        def test__given_stale_provisional_claim__expires_and_recreates_simulation(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
        ):
            stale_start_time = datetime.datetime.now(
                datetime.timezone.utc
            ) - datetime.timedelta(seconds=PROVISIONAL_CLAIM_TTL_SECONDS + 1)
            stale_provisional_impact = create_mock_reform_impact(
                status="computing",
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}job_stale",
                start_time=stale_start_time,
            )
            mock_reform_impacts_service.get_all_reform_impacts.side_effect = [
                [stale_provisional_impact],
                [stale_provisional_impact],
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once_with(
                country_id=MOCK_COUNTRY_ID,
                policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_RESOLVED_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options_hash=MOCK_OPTIONS_HASH,
                message=STALE_PROVISIONAL_IMPACT_MESSAGE,
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}job_stale",
            )
            mock_reform_impacts_service.set_reform_impact.assert_called_once()
            mock_simulation_api.run.assert_called_once()

        def test__given_provisional_promotion_updates_zero_rows__inserts_replacement_tracking_row(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            mock_reform_impacts_service.get_all_reform_impacts.return_value = []
            mock_reform_impacts_service.update_reform_impact_execution_id.return_value = 0

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert mock_reform_impacts_service.set_reform_impact.call_count == 2
            first_insert = mock_reform_impacts_service.set_reform_impact.call_args_list[
                0
            ]
            second_insert = (
                mock_reform_impacts_service.set_reform_impact.call_args_list[1]
            )
            assert (
                first_insert.kwargs["execution_id"]
                == f"{PENDING_EXECUTION_ID_PREFIX}{MOCK_PROCESS_ID}"
            )
            assert second_insert.kwargs["execution_id"] == MOCK_EXECUTION_ID

        def test__given_provisional_promotion_updates_zero_rows_but_newer_claim_exists__does_not_insert_fallback(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            replacement_impact = create_mock_reform_impact(
                status="computing",
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}job_replacement",
                start_time=datetime.datetime.now(datetime.timezone.utc),
            )
            mock_reform_impacts_service.get_all_reform_impacts.side_effect = [
                [],
                [],
                [replacement_impact],
            ]
            mock_reform_impacts_service.update_reform_impact_execution_id.return_value = 0

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert mock_reform_impacts_service.set_reform_impact.call_count == 1
            inserted_execution_id = (
                mock_reform_impacts_service.set_reform_impact.call_args.kwargs[
                    "execution_id"
                ]
            )
            assert (
                inserted_execution_id
                == f"{PENDING_EXECUTION_ID_PREFIX}{MOCK_PROCESS_ID}"
            )

        def test__given_runtime_cache_version__uses_versioned_economy_cache_key(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
            monkeypatch,
        ):
            cache_version = "e1cache01"
            monkeypatch.setattr(
                "policyengine_api.services.economy_service.get_economy_impact_cache_version",
                lambda country_id, api_version=None: cache_version,
            )
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = []

            economy_service.get_economic_impact(**base_params)

            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_POLICY_ID,
                MOCK_BASELINE_POLICY_ID,
                MOCK_REGION,
                MOCK_RESOLVED_DATASET,
                MOCK_TIME_PERIOD,
                MOCK_LOOKUP_OPTIONS_HASH,
                economy_service._build_options_hash_lookup_pattern(
                    MOCK_LOOKUP_OPTIONS_HASH
                ),
                cache_version,
            )

        def test__given_alias_dataset__queries_previous_impacts_with_resolved_bundle(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = []

            economy_service.get_economic_impact(**base_params)

            call_args = mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.call_args.args
            assert call_args[4] == MOCK_RESOLVED_DATASET
            assert call_args[6] == MOCK_LOOKUP_OPTIONS_HASH
            assert call_args[7] == economy_service._build_options_hash_lookup_pattern(
                MOCK_LOOKUP_OPTIONS_HASH
            )
            assert "data_version=" not in call_args[7]
            assert "runtime_app_name" not in call_args[7]

        def test__given_completed_impact__uses_resolved_runtime_bundle_for_cache_lookup(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            mock_simulation_api.resolve_app_name.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_MODEL_VERSION,
            )

        def test__given_cached_impact_and_runtime_lookup_fails__then_returns_cached_result(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                completed_impact
            ]
            mock_simulation_api.resolve_app_name.side_effect = RuntimeError(
                "versions down"
            )

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert (
                result.data["policyengine_bundle"]["dataset"] == MOCK_RESOLVED_DATASET
            )
            mock_simulation_api.run.assert_not_called()

        def test__given_legacy_cached_impact_without_resolved_app_name__then_refreshes_cache(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            completed_impact = create_mock_reform_impact(
                status="ok",
                reform_impact_json=json.dumps(MOCK_REFORM_IMPACT_DATA),
                options_hash=MOCK_LOOKUP_OPTIONS_HASH,
            )
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            mock_simulation_api.resolve_app_name.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_MODEL_VERSION,
            )
            mock_simulation_api.run.assert_called_once()

        def test__given_legacy_and_refreshed_cached_impacts__then_reuses_refreshed_entry(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            legacy_impact = create_mock_reform_impact(
                status="ok",
                reform_impact_json=json.dumps(MOCK_REFORM_IMPACT_DATA),
                options_hash=MOCK_LOOKUP_OPTIONS_HASH,
            )
            refreshed_impact = create_mock_reform_impact(status="ok")
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.side_effect = [
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
            assert (
                mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.call_count
                == 2
            )
            mock_simulation_api.run.assert_not_called()

        def test__given_legacy_cached_impact_and_runtime_lookup_fails__then_returns_cached_result(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            completed_impact = create_mock_reform_impact(
                status="ok",
                reform_impact_json=json.dumps(MOCK_REFORM_IMPACT_DATA),
                options_hash=MOCK_LOOKUP_OPTIONS_HASH,
            )
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                completed_impact
            ]
            mock_simulation_api.resolve_app_name.side_effect = RuntimeError(
                "versions down"
            )

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data["policyengine_bundle"]["model_version"] is None
            mock_simulation_api.run.assert_not_called()

        def test__given_legacy_computing_impact_without_resolved_app_name__then_reuses_execution(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            computing_impact = create_mock_reform_impact(
                status="computing",
                reform_impact_json=json.dumps({}),
            )
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = [
                computing_impact
            ]
            mock_simulation_api.get_execution_status.return_value = "running"

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            mock_simulation_api.resolve_app_name.assert_not_called()
            mock_simulation_api.run.assert_not_called()

        def test__given_exception__raises_error(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.side_effect = Exception(
                "Database error"
            )

            with pytest.raises(Exception) as exc_info:
                economy_service.get_economic_impact(**base_params)
            assert str(exc_info.value) == "Database error"

        def test__given_uk_request__preserves_model_version_in_bundle(
            self,
            economy_service,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_get_policyengine_version,
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            mock_country_package_versions["uk"] = "2.7.8"
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = []

            economy_service.get_economic_impact(
                country_id="uk",
                policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region="uk",
                dataset="default",
                time_period=MOCK_TIME_PERIOD,
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target="general",
            )

            sim_params = mock_simulation_api.run.call_args[0][0]
            assert sim_params["_metadata"]["model_version"] == "2.7.8"

    class TestGetBudgetWindowEconomicImpact:
        @pytest.fixture
        def economy_service(
            self,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_policy_service,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            return EconomyService()

        @pytest.fixture
        def base_params(self):
            return {
                "country_id": MOCK_COUNTRY_ID,
                "policy_id": MOCK_POLICY_ID,
                "baseline_policy_id": MOCK_BASELINE_POLICY_ID,
                "region": MOCK_REGION,
                "dataset": MOCK_DATASET,
                "start_year": "2026",
                "window_size": 3,
                "options": MOCK_OPTIONS,
                "api_version": MOCK_API_VERSION,
                "target": "general",
            }

        def test__given_no_cached_batch__submits_parent_batch_and_returns_queued_result(
            self,
            economy_service,
            base_params,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_budget_window_cache,
        ):
            batch_execution = create_mock_budget_window_batch_execution(
                batch_job_id="fc-budget-123",
                status="submitted",
            )
            mock_simulation_api.run_budget_window_batch.return_value = batch_execution

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 0
            assert result.completed_years == []
            assert result.computing_years == []
            assert result.queued_years == ["2026", "2027", "2028"]
            assert "Queued 2026" in result.message
            mock_simulation_api.run_budget_window_batch.assert_called_once()
            submitted_payload = (
                mock_simulation_api.run_budget_window_batch.call_args.args[0]
            )
            assert submitted_payload["start_year"] == "2026"
            assert submitted_payload["window_size"] == 3
            assert submitted_payload["max_parallel"] == 20
            assert submitted_payload["target"] == "general"
            assert "time_period" not in submitted_payload
            mock_budget_window_cache.claim_batch_start.assert_called_once_with(
                "budget-window-cache-key", MOCK_PROCESS_ID
            )
            mock_budget_window_cache.store_batch_job_id.assert_called_once_with(
                "budget-window-cache-key", "fc-budget-123"
            )
            mock_reform_impacts_service.set_reform_impact.assert_not_called()

        def test__given_completed_cached_result__returns_completed_batch_result(
            self,
            economy_service,
            base_params,
            mock_simulation_api,
            mock_budget_window_cache,
        ):
            completed_result = {
                "kind": "budgetWindow",
                "startYear": "2026",
                "endYear": "2028",
                "windowSize": 3,
                "annualImpacts": [
                    {
                        "year": "2026",
                        "taxRevenueImpact": 100,
                        "federalTaxRevenueImpact": 80,
                        "stateTaxRevenueImpact": 20,
                        "benefitSpendingImpact": -10,
                        "budgetaryImpact": 90,
                    }
                ],
                "totals": {
                    "year": "Total",
                    "taxRevenueImpact": 100,
                    "federalTaxRevenueImpact": 80,
                    "stateTaxRevenueImpact": 20,
                    "benefitSpendingImpact": -10,
                    "budgetaryImpact": 90,
                },
            }
            mock_budget_window_cache.get_completed_result.return_value = (
                completed_result
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.progress == 100
            assert result.data == completed_result
            mock_simulation_api.get_budget_window_batch_by_id.assert_not_called()
            mock_simulation_api.run_budget_window_batch.assert_not_called()

        def test__given_cached_batch_id__returns_running_batch_progress(
            self,
            economy_service,
            base_params,
            mock_simulation_api,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_batch_job_id.return_value = "fc-budget-123"
            mock_simulation_api.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="running",
                    progress=33,
                    completed_years=["2026"],
                    running_years=["2027"],
                    queued_years=["2028"],
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 33
            assert result.completed_years == ["2026"]
            assert result.computing_years == ["2027"]
            assert result.queued_years == ["2028"]
            assert "1 of 3 complete" in result.message
            mock_simulation_api.get_budget_window_batch_by_id.assert_called_once_with(
                "fc-budget-123"
            )

        def test__given_completed_batch_poll__caches_result_and_returns_completed(
            self,
            economy_service,
            base_params,
            mock_simulation_api,
            mock_budget_window_cache,
        ):
            completed_result = {
                "kind": "budgetWindow",
                "startYear": "2026",
                "endYear": "2028",
                "windowSize": 3,
                "annualImpacts": [],
                "totals": {},
            }
            mock_budget_window_cache.get_batch_job_id.return_value = "fc-budget-123"
            mock_simulation_api.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="complete",
                    progress=100,
                    completed_years=["2026", "2027", "2028"],
                    result=completed_result,
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data == completed_result
            mock_budget_window_cache.set_completed_result.assert_called_once_with(
                "budget-window-cache-key", completed_result
            )
            mock_budget_window_cache.clear_batch_job_id.assert_called_once_with(
                "budget-window-cache-key"
            )

        def test__given_failed_batch_poll__returns_failed(
            self,
            economy_service,
            base_params,
            mock_simulation_api,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.get_batch_job_id.return_value = "fc-budget-123"
            mock_simulation_api.get_budget_window_batch_by_id.return_value = (
                create_mock_budget_window_batch_execution(
                    batch_job_id="fc-budget-123",
                    status="failed",
                    progress=33,
                    completed_years=["2026"],
                    queued_years=["2028"],
                    failed_years=["2027"],
                    error="Budget window failed for 2027",
                )
            )

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.ERROR
            assert result.error == "Budget window failed for 2027"
            assert result.completed_years == ["2026"]
            assert result.computing_years == []
            assert result.queued_years == ["2028"]
            mock_budget_window_cache.set_completed_result.assert_not_called()

        def test__given_existing_start_claim__does_not_submit_duplicate_batch(
            self,
            economy_service,
            base_params,
            mock_simulation_api,
            mock_budget_window_cache,
        ):
            mock_budget_window_cache.claim_batch_start.return_value = False

            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.progress == 0
            assert result.queued_years == ["2026", "2027", "2028"]
            mock_simulation_api.run_budget_window_batch.assert_not_called()

        def test__given_batch_submission_fails__clears_start_claim(
            self,
            economy_service,
            base_params,
            mock_simulation_api,
            mock_budget_window_cache,
        ):
            mock_simulation_api.run_budget_window_batch.side_effect = RuntimeError(
                "submit failed"
            )

            with pytest.raises(RuntimeError, match="submit failed"):
                economy_service.get_budget_window_economic_impact(**base_params)

            mock_budget_window_cache.clear_starting_claim.assert_called_once_with(
                "budget-window-cache-key", MOCK_PROCESS_ID
            )

        def test__given_cliff_target__raises_value_error(
            self, economy_service, base_params
        ):
            base_params["target"] = "cliff"

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
                    f"budget-window end_year must be {BUDGET_WINDOW_MAX_END_YEAR} or earlier"
                ),
            ):
                economy_service.get_budget_window_economic_impact(**base_params)

        def test__given_runtime_cache_version__uses_versioned_cache_key_for_budget_window(
            self,
            economy_service,
            base_params,
            mock_country_package_versions,
            mock_get_dataset_version,
            mock_simulation_api,
            mock_budget_window_cache,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
            monkeypatch,
        ):
            cache_version = "e1cache01"

            monkeypatch.setattr(
                "policyengine_api.services.economy_service.get_economy_impact_cache_version",
                lambda country_id, api_version=None: cache_version,
            )
            result = economy_service.get_budget_window_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            cache_key_kwargs = mock_budget_window_cache.build_key.call_args.kwargs
            assert cache_key_kwargs["time_period"] == "budget_window:2026:3"
            assert cache_key_kwargs["api_version"] == cache_version

    class TestGetPreviousImpacts:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        def test_given_valid_parameters_calls_service_correctly(
            self, economy_service, mock_reform_impacts_service
        ):
            expected_impacts = [create_mock_reform_impact()]
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = expected_impacts

            result = economy_service._get_previous_impacts(
                MOCK_COUNTRY_ID,
                MOCK_POLICY_ID,
                MOCK_BASELINE_POLICY_ID,
                MOCK_REGION,
                MOCK_DATASET,
                MOCK_TIME_PERIOD,
                MOCK_OPTIONS_HASH,
                MOCK_API_VERSION,
            )

            assert result == expected_impacts
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_POLICY_ID,
                MOCK_BASELINE_POLICY_ID,
                MOCK_REGION,
                MOCK_DATASET,
                MOCK_TIME_PERIOD,
                MOCK_OPTIONS_HASH,
                economy_service._build_options_hash_lookup_pattern(MOCK_OPTIONS_HASH),
                MOCK_API_VERSION,
            )

    class TestGetMostRecentImpact:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.fixture
        def setup_options(self):
            return EconomicImpactSetupOptions(
                process_id=MOCK_PROCESS_ID,
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
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = impacts

            result = economy_service._get_most_recent_impact(setup_options)

            assert result == impacts[0]

        def test__given_exact_and_prefix_matches__prefers_exact_options_hash(
            self, economy_service, setup_options, mock_reform_impacts_service
        ):
            impacts = [
                create_mock_reform_impact(options_hash=MOCK_LOOKUP_OPTIONS_HASH),
                create_mock_reform_impact(options_hash=MOCK_OPTIONS_HASH),
            ]
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = impacts

            result = economy_service._get_most_recent_impact(setup_options)

            assert result == impacts[1]

        def test__given_no_impacts__returns_none(
            self, economy_service, setup_options, mock_reform_impacts_service
        ):
            # Arrange
            mock_reform_impacts_service.get_all_reform_impacts_by_options_hash_prefix.return_value = []

            # Act
            result = economy_service._get_most_recent_impact(setup_options)

            # Assert
            assert result is None

    class TestGetExistingEconomicImpact:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.fixture
        def setup_options(self):
            return EconomicImpactSetupOptions(
                process_id=MOCK_PROCESS_ID,
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

        def test__given_stale_provisional_impact__returns_none(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
        ):
            stale_impact = create_mock_reform_impact(
                status="computing",
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}job_stale",
                start_time=datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(seconds=PROVISIONAL_CLAIM_TTL_SECONDS + 1),
            )
            mock_reform_impacts_service.get_all_reform_impacts.return_value = [
                stale_impact
            ]

            result = economy_service._get_existing_economic_impact(setup_options)

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

        def test__given_error_status__returns_error(self, economy_service):
            impact = create_mock_reform_impact(status="error")

            result = economy_service._determine_impact_action(impact)

            assert result == ImpactAction.ERROR

        def test__given_computing_status__returns_computing(self, economy_service):
            impact = create_mock_reform_impact(status="computing")

            result = economy_service._determine_impact_action(impact)

            assert result == ImpactAction.COMPUTING

        def test__given_stale_provisional_computing_status__returns_create(
            self, economy_service
        ):
            impact = create_mock_reform_impact(
                status="computing",
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}job_stale",
                start_time=datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(seconds=PROVISIONAL_CLAIM_TTL_SECONDS + 1),
            )

            result = economy_service._determine_impact_action(impact)

            assert result == ImpactAction.CREATE

        def test__given_unknown_status__raises_error(self, economy_service):
            impact = create_mock_reform_impact(status="unknown")

            with pytest.raises(ValueError) as exc_info:
                economy_service._determine_impact_action(impact)
            assert "Unknown impact status: unknown" in str(exc_info.value)

    class TestHandleExecutionState:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.fixture
        def setup_options(self):
            return EconomicImpactSetupOptions(
                process_id=MOCK_PROCESS_ID,
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

        def test__given_succeeded_state__returns_completed_result(
            self,
            economy_service,
            setup_options,
            mock_simulation_api,
            mock_reform_impacts_service,
            mock_logger,
        ):
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_simulation_api.get_execution_result.return_value = (
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

        def test__given_failed_state__returns_error_result(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
            mock_logger,
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            result = economy_service._handle_execution_state(
                setup_options, "failed", reform_impact
            )

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.message == "Simulation API execution failed"
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        def test__given_active_state__returns_computing_result(
            self, economy_service, setup_options, mock_logger
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact
            )

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        def test__given_provisional_claim__returns_computing_without_polling(
            self, economy_service, setup_options, mock_simulation_api, mock_logger
        ):
            reform_impact = create_mock_reform_impact(
                status="computing",
                execution_id=f"{PENDING_EXECUTION_ID_PREFIX}job_pending",
            )

            result = economy_service._handle_computing_impact(
                setup_options, reform_impact
            )

            assert result.status == ImpactStatus.COMPUTING
            mock_simulation_api.get_execution_by_id.assert_not_called()

        def test__given_unknown_state__raises_error(
            self, economy_service, setup_options
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            with pytest.raises(ValueError) as exc_info:
                economy_service._handle_execution_state(
                    setup_options, "UNKNOWN", reform_impact
                )
            assert "Unexpected sim API execution state: UNKNOWN" in str(exc_info.value)

        # Modal status tests
        def test__given_modal_complete_state__then_returns_completed_result(
            self,
            economy_service,
            setup_options,
            mock_simulation_api,
            mock_reform_impacts_service,
            mock_logger,
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_simulation_api.get_execution_result.return_value = (
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

        def test__given_modal_failed_state__then_returns_error_result(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
            mock_logger,
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
            assert result.message == "Simulation API execution failed"
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        def test__given_modal_failed_state_with_error_message__then_includes_error_in_message(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
            mock_logger,
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
            assert (
                result.message
                == "Simulation API execution failed: Simulation timed out"
            )
            # Verify the error message was passed to the service
            call_args = mock_reform_impacts_service.set_error_reform_impact.call_args
            assert "Simulation timed out" in call_args[1]["message"]

        def test__given_modal_running_state__then_returns_computing_result(
            self, economy_service, setup_options, mock_logger
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

        def test__given_modal_submitted_state__then_returns_computing_result(
            self, economy_service, setup_options, mock_logger
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

    class TestCreateProcessId:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        def test_given_mocked_datetime_and_random_returns_expected_format(
            self, economy_service, mock_datetime, mock_numpy_random
        ):
            result = economy_service._create_process_id()

            assert result == "job_20250626120000_1234"
            mock_datetime.now.assert_called_once()
            mock_numpy_random.assert_called_once_with(1000, 9999)


class TestEconomicImpactResult:
    class TestToDict:
        def test__given_completed_result__returns_correct_dict(self):
            result = EconomicImpactResult.completed(MOCK_REFORM_IMPACT_DATA)

            result_dict = result.to_dict()

            assert result_dict == {
                "status": "ok",
                "data": MOCK_REFORM_IMPACT_DATA,
            }

        def test__given_computing_result__returns_correct_dict(self):
            result = EconomicImpactResult.computing()

            result_dict = result.to_dict()

            assert result_dict == {"status": "computing", "data": None}

        def test__given_error_result__returns_correct_dict(self):
            with patch("policyengine_api.services.economy_service.logger"):
                result = EconomicImpactResult.error("Test error message")

            result_dict = result.to_dict()

            assert result_dict == {"status": "error", "data": None}

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
            process_id=MOCK_PROCESS_ID,
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

        assert options.process_id == MOCK_PROCESS_ID
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
        GCS paths in the data field (not None).
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
                self.test_country_id,
                self.test_reform_policy,
                self.test_current_law_baseline_policy,
                self.test_region,
                self.test_time_period,
                self.test_scope,
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
            assert (
                sim_options["data"] == "gs://policyengine-us-data/enhanced_cps_2024.h5"
            )

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
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                time_period,
                scope,
            )
            sim_options = sim_options_model.model_dump()

            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ca"
            assert sim_options["data"] == "gs://policyengine-us-data/states/CA.h5"

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
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                time_period,
                scope,
            )
            sim_options = sim_options_model.model_dump()

            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ut"
            assert sim_options["data"] == "gs://policyengine-us-data/states/UT.h5"

        def test__given_cliff_target__returns_correct_sim_options(self):
            country_id = "us"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "us"
            time_period = 2025
            scope = "macro"

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                time_period,
                scope,
                include_cliffs=True,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == region
            assert (
                sim_options["data"] == "gs://policyengine-us-data/enhanced_cps_2024.h5"
            )
            assert sim_options["include_cliffs"] is True

        def test__given_uk__returns_correct_sim_options(self):
            country_id = "uk"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "uk"
            time_period = 2025
            scope = "macro"

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                time_period,
                scope,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["country"] == country_id
            assert sim_options["region"] == region
            assert (
                sim_options["data"]
                == "gs://policyengine-uk-data-private/enhanced_frs_2023_24.h5"
            )

        def test__given_congressional_district__returns_correct_sim_options(
            self,
        ):
            country_id = "us"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "congressional_district/CA-37"  # Pre-normalized
            time_period = 2025
            scope = "macro"

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                time_period,
                scope,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["region"] == "congressional_district/CA-37"
            assert sim_options["data"] == "gs://policyengine-us-data/districts/CA-37.h5"

        def test__given_explicit_dataset__returns_named_dataset(self):
            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                self.test_country_id,
                self.test_reform_policy,
                self.test_current_law_baseline_policy,
                self.test_region,
                self.test_time_period,
                self.test_scope,
                dataset="enhanced_cps",
            )

            sim_options = sim_options_model.model_dump()
            assert (
                sim_options["data"]
                == "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5@1.77.0"
            )

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
            with pytest.raises(ValueError) as exc_info:
                service._setup_region("us", "state/mb")
            assert "Invalid US state: 'mb'" in str(exc_info.value)

        def test__given_invalid_congressional_district__raises_value_error(
            self,
        ):
            service = EconomyService()
            with pytest.raises(ValueError) as exc_info:
                service._setup_region("us", "congressional_district/cruft")
            assert "Invalid congressional district: 'cruft'" in str(exc_info.value)

        def test__given_invalid_prefix__raises_value_error(self):
            service = EconomyService()
            with pytest.raises(ValueError) as exc_info:
                service._setup_region("us", "invalid_prefix/tx")
            assert "Invalid US region: 'invalid_prefix/tx'" in str(exc_info.value)

        def test__given_invalid_bare_value__raises_value_error(self):
            # Bare values without prefix are now invalid (should be normalized first)
            service = EconomyService()
            with pytest.raises(ValueError) as exc_info:
                service._setup_region("us", "invalid_value")
            assert "Invalid US region: 'invalid_value'" in str(exc_info.value)

        def test__given_place_region__returns_unchanged(self):
            # Test normalized "place/STATE-FIPS" format passes through
            service = EconomyService()
            result = service._setup_region("us", "place/NJ-57000")
            assert result == "place/NJ-57000"

        def test__given_invalid_place_format__raises_value_error(self):
            # Test place without hyphen raises error
            service = EconomyService()
            with pytest.raises(ValueError) as exc_info:
                service._setup_region("us", "place/invalid")
            assert "Invalid place format" in str(exc_info.value)

        def test__given_invalid_place_state__raises_value_error(self):
            # Test place with invalid state code raises error
            service = EconomyService()
            with pytest.raises(ValueError) as exc_info:
                service._setup_region("us", "place/XX-57000")
            assert "Invalid state in place code" in str(exc_info.value)

        def test__given_invalid_place_fips__raises_value_error(self):
            # Test place with invalid FIPS code raises error
            service = EconomyService()
            with pytest.raises(ValueError) as exc_info:
                service._setup_region("us", "place/NJ-abc")
            assert "Invalid FIPS code" in str(exc_info.value)

    class TestSetupData:
        """Tests for _setup_data method.

        Note: _setup_data now uses get_default_dataset from policyengine package
        to return GCS paths for all region types (not None).
        """

        def test__given_us_place__returns_state_dataset(self):
            # Test with place region - uses parent state's dataset
            service = EconomyService()
            result = service._setup_data("us", "place/NJ-57000")
            assert result == "gs://policyengine-us-data/states/NJ.h5"

        def test__given_us_state_ca__returns_state_dataset(self):
            # Test with US state - returns state-specific dataset
            service = EconomyService()
            result = service._setup_data("us", "state/ca")
            assert result == "gs://policyengine-us-data/states/CA.h5"

        def test__given_us_state_ut__returns_state_dataset(self):
            # Test with Utah state - returns state-specific dataset
            service = EconomyService()
            result = service._setup_data("us", "state/ut")
            assert result == "gs://policyengine-us-data/states/UT.h5"

        def test__given_us_nationwide__returns_cps_dataset(self):
            # Test with US nationwide region
            service = EconomyService()
            result = service._setup_data("us", "us")
            assert result == "gs://policyengine-us-data/enhanced_cps_2024.h5"

        def test__given_congressional_district__returns_district_dataset(self):
            # Test with congressional district - returns district-specific dataset
            service = EconomyService()
            result = service._setup_data("us", "congressional_district/CA-37")
            assert result == "gs://policyengine-us-data/districts/CA-37.h5"

        def test__given_uk__returns_efrs_dataset(self):
            # Test with UK - returns enhanced FRS dataset
            service = EconomyService()
            result = service._setup_data("uk", "uk")
            assert result == "gs://policyengine-uk-data-private/enhanced_frs_2023_24.h5"

        def test__given_invalid_country__raises_value_error(self, mock_logger):
            # Test with invalid country
            service = EconomyService()
            with pytest.raises(ValueError) as exc_info:
                service._setup_data("invalid", "region")
            assert "invalid" in str(exc_info.value).lower()

        def test__given_passthrough_dataset__returns_dataset_directly(self):
            # Test with passthrough dataset (national-with-breakdowns)
            service = EconomyService()
            result = service._setup_data("us", "us", dataset="national-with-breakdowns")
            assert result == "national-with-breakdowns"

        def test__given_passthrough_test_dataset__returns_dataset_directly(
            self,
        ):
            # Test with passthrough test dataset
            service = EconomyService()
            result = service._setup_data(
                "us", "us", dataset="national-with-breakdowns-test"
            )
            assert result == "national-with-breakdowns-test"

        def test__given_explicit_us_enhanced_cps__returns_named_dataset(self):
            service = EconomyService()
            result = service._setup_data("us", "us", dataset="enhanced_cps")
            assert (
                result
                == "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5@1.77.0"
            )

        def test__given_explicit_us_cps__returns_named_dataset(self):
            service = EconomyService()
            result = service._setup_data("us", "us", dataset="cps")
            assert result == "hf://policyengine/policyengine-us-data/cps_2023.h5@1.77.0"

        def test__given_explicit_uk_enhanced_frs__returns_named_dataset(self):
            service = EconomyService()
            result = service._setup_data("uk", "uk", dataset="enhanced_frs")
            assert (
                result
                == "hf://policyengine/policyengine-uk-data-private/enhanced_frs_2023_24.h5@1.40.3"
            )

        def test__given_default_dataset__uses_get_default_dataset(self):
            # Test that "default" falls through to get_default_dataset
            service = EconomyService()
            result = service._setup_data("us", "state/ca", dataset="default")
            assert result == "gs://policyengine-us-data/states/CA.h5"

        def test__given_unknown_dataset__uses_get_default_dataset(self):
            # Test that unknown dataset values fall through to get_default_dataset
            service = EconomyService()
            result = service._setup_data("us", "state/ca", dataset="unknown-dataset")
            assert result == "gs://policyengine-us-data/states/CA.h5"

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
            with pytest.raises(ValueError) as exc_info:
                service._validate_us_region("state/mb")
            assert "Invalid US state: 'mb'" in str(exc_info.value)

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
            with pytest.raises(ValueError) as exc_info:
                service._validate_us_region("congressional_district/CA-99")
            assert "Invalid congressional district: 'CA-99'" in str(exc_info.value)

        def test__given_nonexistent_district__raises_value_error(self):
            service = EconomyService()
            with pytest.raises(ValueError) as exc_info:
                service._validate_us_region("congressional_district/cruft")
            assert "Invalid congressional district: 'cruft'" in str(exc_info.value)
