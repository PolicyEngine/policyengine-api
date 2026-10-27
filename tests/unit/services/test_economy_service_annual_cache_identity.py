"""Annual economic impacts: cache keys, runtime bundles and legacy cached impacts."""

import json
from unittest.mock import patch

import pytest

from policyengine_api.runtime_cache.reform_impacts import (
    ReformImpactIdentity,
    ReformImpactScope,
)
from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_service import ImpactStatus
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_COUNTRY_ID,
    MOCK_DATA_VERSION,
    MOCK_DATASET,
    MOCK_LOOKUP_OPTIONS_HASH,
    MOCK_MODEL_VERSION,
    MOCK_OBSERVABILITY_ID,
    MOCK_OPTIONS,
    MOCK_POLICY_ID,
    MOCK_POLICYENGINE_VERSION,
    MOCK_REFORM_IMPACT_DATA,
    MOCK_REGION,
    MOCK_RESOLVED_DATASET,
    MOCK_TIME_PERIOD,
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
