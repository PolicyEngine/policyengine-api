"""Stored reform impacts: lookup, impact actions, claim tokens and options hashes."""

import pytest

from policyengine_api.runtime_cache.reform_impacts import (
    ReformImpactIdentity,
    ReformImpactScope,
)
from policyengine_api.services.economy_service import (
    EconomicImpactSetupOptions,
    EconomyService,
    ImpactAction,
    RuntimeBundleIdentity,
)
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
    MOCK_OPTIONS_HASH,
    MOCK_POLICY_ID,
    MOCK_POLICYENGINE_VERSION,
    MOCK_REGION,
    MOCK_RESOLVED_DATASET,
    MOCK_SUBMISSION_CLAIM_ID,
    MOCK_TIME_PERIOD,
    create_mock_reform_impact,
)
from tests.fixtures.services.economy_service_helpers import (
    hash_prefix_lookup,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomyService:
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

    class TestCreateSubmissionClaimId:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        def test_returns_uuid_string(self, economy_service, mock_submission_claim_id):
            result = economy_service._create_submission_claim_id()

            assert result == MOCK_SUBMISSION_CLAIM_ID
            mock_submission_claim_id.assert_called_once_with()


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
