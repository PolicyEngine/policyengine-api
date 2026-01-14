import json
import pytest
from unittest.mock import patch, MagicMock
from typing import Literal

from policyengine_api.services.economy_service import (
    EconomyService,
    EconomicImpactResult,
    EconomicImpactSetupOptions,
    ImpactAction,
    ImpactStatus,
)
from tests.fixtures.services.economy_service import (
    MOCK_COUNTRY_ID,
    MOCK_POLICY_ID,
    MOCK_BASELINE_POLICY_ID,
    MOCK_REGION,
    MOCK_DATASET,
    MOCK_TIME_PERIOD,
    MOCK_API_VERSION,
    MOCK_OPTIONS,
    MOCK_OPTIONS_HASH,
    MOCK_EXECUTION_ID,
    MOCK_PROCESS_ID,
    MOCK_REFORM_IMPACT_DATA,
    create_mock_reform_impact,
    mock_country_package_versions,
    mock_datetime,
    mock_get_dataset_version,
    mock_logger,
    mock_numpy_random,
    mock_policy_service,
    mock_reform_impacts_service,
    mock_simulation_api,
)


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
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            completed_impact = create_mock_reform_impact(status="ok")
            mock_reform_impacts_service.get_all_reform_impacts.return_value = [
                completed_impact
            ]

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data == MOCK_REFORM_IMPACT_DATA
            mock_reform_impacts_service.get_all_reform_impacts.assert_called_once()
            mock_simulation_api.run.assert_not_called()

        def test__given_computing_impact_with_succeeded_execution__returns_completed_result(
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
            computing_impact = create_mock_reform_impact(status="computing")
            mock_reform_impacts_service.get_all_reform_impacts.return_value = [
                computing_impact
            ]
            mock_simulation_api.get_execution_status.return_value = "SUCCEEDED"
            mock_simulation_api.get_execution_result.return_value = (
                MOCK_REFORM_IMPACT_DATA
            )

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.OK
            assert result.data == MOCK_REFORM_IMPACT_DATA
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
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            computing_impact = create_mock_reform_impact(status="computing")
            mock_reform_impacts_service.get_all_reform_impacts.return_value = [
                computing_impact
            ]
            mock_simulation_api.get_execution_status.return_value = "FAILED"

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
            mock_policy_service,
            mock_reform_impacts_service,
            mock_simulation_api,
            mock_logger,
            mock_datetime,
            mock_numpy_random,
        ):
            computing_impact = create_mock_reform_impact(status="computing")
            mock_reform_impacts_service.get_all_reform_impacts.return_value = [
                computing_impact
            ]
            mock_simulation_api.get_execution_status.return_value = "ACTIVE"

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        def test__given_no_previous_impact__creates_new_simulation(
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

            result = economy_service.get_economic_impact(**base_params)

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None
            mock_simulation_api.run.assert_called_once()
            mock_reform_impacts_service.set_reform_impact.assert_called_once()

        def test__given_exception__raises_error(
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
            mock_reform_impacts_service.get_all_reform_impacts.side_effect = Exception(
                "Database error"
            )

            with pytest.raises(Exception) as exc_info:
                economy_service.get_economic_impact(**base_params)
            assert str(exc_info.value) == "Database error"

    class TestGetPreviousImpacts:

        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        def test_given_valid_parameters_calls_service_correctly(
            self, economy_service, mock_reform_impacts_service
        ):
            expected_impacts = [create_mock_reform_impact()]
            mock_reform_impacts_service.get_all_reform_impacts.return_value = (
                expected_impacts
            )

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
            mock_reform_impacts_service.get_all_reform_impacts.assert_called_once_with(
                MOCK_COUNTRY_ID,
                MOCK_POLICY_ID,
                MOCK_BASELINE_POLICY_ID,
                MOCK_REGION,
                MOCK_DATASET,
                MOCK_TIME_PERIOD,
                MOCK_OPTIONS_HASH,
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
                dataset=MOCK_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target="general",
                options_hash=MOCK_OPTIONS_HASH,
            )

        def test__given_existing_impacts__returns_first_impact(
            self, economy_service, setup_options, mock_reform_impacts_service
        ):
            impacts = [
                create_mock_reform_impact(),
                create_mock_reform_impact(),
            ]
            mock_reform_impacts_service.get_all_reform_impacts.return_value = impacts

            result = economy_service._get_most_recent_impact(setup_options)

            assert result == impacts[0]

        def test__given_no_impacts__returns_none(
            self, economy_service, setup_options, mock_reform_impacts_service
        ):
            # Arrange
            mock_reform_impacts_service.get_all_reform_impacts.return_value = []

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

        def test__given_error_status__returns_completed(self, economy_service):
            impact = create_mock_reform_impact(status="error")

            result = economy_service._determine_impact_action(impact)

            assert result == ImpactAction.COMPLETED

        def test__given_computing_status__returns_computing(self, economy_service):
            impact = create_mock_reform_impact(status="computing")

            result = economy_service._determine_impact_action(impact)

            assert result == ImpactAction.COMPUTING

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
                dataset=MOCK_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target="general",
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
                setup_options, "SUCCEEDED", reform_impact, mock_execution
            )

            assert result.status == ImpactStatus.OK
            assert result.data == MOCK_REFORM_IMPACT_DATA
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
                setup_options, "FAILED", reform_impact
            )

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        def test__given_active_state__returns_computing_result(
            self, economy_service, setup_options, mock_logger
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            result = economy_service._handle_execution_state(
                setup_options, "ACTIVE", reform_impact
            )

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

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
            assert result.data == MOCK_REFORM_IMPACT_DATA
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
                sim_options["data"]
                == "gs://policyengine-us-data/enhanced_cps_2024.h5"
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
                sim_options["data"]
                == "gs://policyengine-us-data/enhanced_cps_2024.h5"
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

        def test__given_city_nyc__returns_unchanged(self):
            # Test normalized "city/nyc" format passes through
            service = EconomyService()
            result = service._setup_region("us", "city/nyc")
            assert result == "city/nyc"

    class TestSetupData:
        """Tests for _setup_data method.

        Note: _setup_data now uses get_default_dataset from policyengine package
        to return GCS paths for all region types (not None).
        """

        def test__given_us_city_nyc__returns_pooled_cps(self):
            # Test with normalized city/nyc format
            service = EconomyService()
            result = service._setup_data("us", "city/nyc")
            assert result == "gs://policyengine-us-data/pooled_3_year_cps_2023.h5"

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
