"""Annual economic impacts: the simulation API payload, breakdowns and refusals."""

from dataclasses import replace
from unittest.mock import MagicMock

import httpx
import pytest

from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_service import EconomyService, ImpactStatus
from policyengine_api.services.policy_service import PolicyService
from tests.fixtures.services.economy_service import (
    ECONOMY_SERVICE_LOGGER_MODULES,
    MOCK_BASELINE_POLICY_ID,
    MOCK_COUNTRY_ID,
    MOCK_DATASET,
    MOCK_MODEL_VERSION,
    MOCK_OBSERVABILITY_ID,
    MOCK_POLICY_ID,
    MOCK_POLICYENGINE_VERSION,
    MOCK_RESOLVED_APP_NAME,
    MOCK_SUBMISSION_CLAIM_ID,
    MOCK_TIME_PERIOD,
)
from tests.fixtures.services.economy_service_helpers import (
    GetEconomicImpactFixtures,
    hash_prefix_lookup,
    make_http_status_error,
    uk_breakdown_request,
)
from tests.fixtures.spm import worker_spm_capability

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomyService:
    class TestGetEconomicImpact(GetEconomicImpactFixtures):
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
            silent_logger = MagicMock()
            for module_name in ECONOMY_SERVICE_LOGGER_MODULES:
                monkeypatch.setattr(f"{module_name}.logger", silent_logger)

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
