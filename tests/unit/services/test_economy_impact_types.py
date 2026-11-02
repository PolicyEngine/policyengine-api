"""The economy service's result and setup option types."""

from unittest.mock import patch

import pytest

from policyengine_api.services.economy_service import (
    EconomicImpactResult,
    EconomicImpactSetupOptions,
    ImpactStatus,
)
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_COUNTRY_ID,
    MOCK_DATASET,
    MOCK_OBSERVABILITY_ID,
    MOCK_OPTIONS,
    MOCK_OPTIONS_HASH,
    MOCK_POLICY_ID,
    MOCK_REFORM_IMPACT_DATA,
    MOCK_REGION,
    MOCK_SUBMISSION_CLAIM_ID,
    MOCK_TIME_PERIOD,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


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
            with patch("policyengine_api.services.economy_impact_types.logger"):
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
                "policyengine_api.services.economy_impact_types.logger"
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
