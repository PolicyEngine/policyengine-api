"""Annual economic impacts answered from a stored reform impact."""

import json

import pytest

from policyengine_api.services.economy_service import ImpactStatus
from tests.fixtures.services.economy_service import (
    MOCK_COUNTRY_ID,
    MOCK_DATA_VERSION,
    MOCK_EXECUTION_ID,
    MOCK_LOOKUP_OPTIONS_HASH,
    MOCK_MODEL_VERSION,
    MOCK_POLICYENGINE_VERSION,
    MOCK_REFORM_IMPACT_DATA,
    MOCK_RESOLVED_DATASET,
    create_mock_reform_impact,
)
from tests.fixtures.services.economy_service_helpers import (
    GetEconomicImpactFixtures,
    hash_prefix_lookup,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomyService:
    class TestGetEconomicImpact(GetEconomicImpactFixtures):
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
