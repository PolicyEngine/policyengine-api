"""Annual economic impacts: claiming and submitting a new simulation."""

from unittest.mock import call, patch

import pytest

from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.runtime_cache.reform_impacts import ReformImpactStartClaim
from policyengine_api.services.economy_service import (
    REFORM_IMPACT_START_CLAIM_ATTEMPTS,
    ImpactStatus,
)
from policyengine_api.services.reform_impacts_service import ReformImpactHandoffError
from tests.fixtures.services.economy_service import (
    MOCK_OBSERVABILITY_ID,
    MOCK_OPTIONS,
    MOCK_OPTIONS_HASH,
)
from tests.fixtures.services.economy_service_helpers import (
    GetEconomicImpactFixtures,
    hash_prefix_lookup,
)
from tests.fixtures.spm import resolved_options

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
