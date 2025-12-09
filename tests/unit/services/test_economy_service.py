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
            mock_reform_impacts_service.get_all_reform_impacts.return_value = (
                []
            )

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
            mock_reform_impacts_service.get_all_reform_impacts.side_effect = (
                Exception("Database error")
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
            mock_reform_impacts_service.get_all_reform_impacts.return_value = (
                impacts
            )

            result = economy_service._get_most_recent_impact(setup_options)

            assert result == impacts[0]

        def test__given_no_impacts__returns_none(
            self, economy_service, setup_options, mock_reform_impacts_service
        ):
            # Arrange
            mock_reform_impacts_service.get_all_reform_impacts.return_value = (
                []
            )

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

        def test__given_computing_status__returns_computing(
            self, economy_service
        ):
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
            assert "Unexpected sim API execution state: UNKNOWN" in str(
                exc_info.value
            )

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
        test_country_id = "us"
        test_reform_policy = json.dumps(
            {"sample_param": {"2024-01-01.2100-12-31": 15}}
        )
        test_current_law_baseline_policy = json.dumps({})
        test_region = "us"
        test_dataset = None
        test_time_period = 2025
        test_scope: Literal["macro"] = "macro"

        def test__given_valid_options__returns_correct_sim_options(self):

            # Create an instance of the class
            service = EconomyService()

            # Call the method with the test data; patch setup_region and setup_data methods
            sim_options_model = service._setup_sim_options(
                self.test_country_id,
                self.test_reform_policy,
                self.test_current_law_baseline_policy,
                self.test_region,
                self.test_dataset,
                self.test_time_period,
                self.test_scope,
            )

            sim_options = sim_options_model.model_dump()

            # Assert the expected values in the returned dictionary
            assert sim_options["country"] == self.test_country_id
            assert sim_options["scope"] == self.test_scope
            assert sim_options["reform"] == json.loads(self.test_reform_policy)
            assert sim_options["baseline"] == json.loads(
                self.test_current_law_baseline_policy
            )
            assert sim_options["time_period"] == self.test_time_period
            assert sim_options["region"] == "us"
            assert sim_options["data"] == None

        def test__given_us_state__returns_correct_sim_options(self):
            # Test with a US state
            country_id = "us"
            reform_policy = json.dumps(
                {"sample_param": {"2024-01-01.2100-12-31": 15}}
            )
            current_law_baseline_policy = json.dumps({})
            region = "ca"
            dataset = None
            time_period = 2025
            scope = "macro"

            # Create an instance of the class
            service = EconomyService()
            # Call the method
            sim_options_model = service._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                dataset,
                time_period,
                scope,
            )
            # Assert the expected values in the returned dictionary
            sim_options = sim_options_model.model_dump()
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(
                current_law_baseline_policy
            )
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ca"
            assert sim_options["data"] is None

        def test__given_enhanced_cps_state__returns_correct_sim_options(self):
            # Test with enhanced_cps dataset
            country_id = "us"
            reform_policy = json.dumps(
                {"sample_param": {"2024-01-01.2100-12-31": 15}}
            )
            current_law_baseline_policy = json.dumps({})
            region = "ut"
            dataset = "enhanced_cps"
            time_period = 2025
            scope = "macro"

            # Create an instance of the class
            service = EconomyService()
            # Call the method
            sim_options_model = service._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                dataset,
                time_period,
                scope,
            )
            sim_options = sim_options_model.model_dump()
            # Assert the expected values in the returned dictionary
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(
                current_law_baseline_policy
            )
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ut"
            assert (
                sim_options["data"]
                == "gs://policyengine-us-data/enhanced_cps_2024.h5"
            )

        def test__given_cliff_target__returns_correct_sim_options(self):
            country_id = "us"
            reform_policy = json.dumps(
                {"sample_param": {"2024-01-01.2100-12-31": 15}}
            )
            current_law_baseline_policy = json.dumps({})
            region = "us"
            dataset = None
            time_period = 2025
            scope = "macro"
            target = "cliff"

            # Create an instance of the class
            service = EconomyService()

            # Call the method
            sim_options_model = service._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                dataset,
                time_period,
                scope,
                include_cliffs=target == "cliff",
            )

            # Assert the expected values in the returned dictionary
            sim_options = sim_options_model.model_dump()
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(
                current_law_baseline_policy
            )
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == region
            assert sim_options["data"] == None
            assert sim_options["include_cliffs"] == True

    class TestSetupRegion:
        def test__given_us_state__returns_correct_region(self):
            # Test with a US state
            country_id = "us"
            # US states always lowercase two-letter codes
            region = "ca"

            # Create an instance of the class
            service = EconomyService()

            # Call the method
            result = service._setup_region(country_id, region)
            # Assert the expected value
            assert result == "state/ca"

        def test__given_non_us_state__returns_correct_region(self):
            # Test with non-US region
            country_id = "uk"
            region = "country/england"

            # Create an instance of the class
            service = EconomyService()
            # Call the method
            result = service._setup_region(country_id, region)
            # Assert the expected value
            assert result == region

    class TestSetupData:
        def test__given_enhanced_cps_dataset__returns_correct_gcp_path(self):
            # Test with enhanced_cps dataset
            dataset = "enhanced_cps"
            country_id = "us"
            region = "us"

            # Create an instance of the class
            service = EconomyService()
            # Call the method
            result = service._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result == "gs://policyengine-us-data/enhanced_cps_2024.h5"

        def test__given_us_state_dataset__returns_none(self):
            # Test with US state dataset - should return None
            dataset = "us_state"
            country_id = "us"
            region = "ca"

            # Create an instance of the class
            service = EconomyService()
            # Call the method
            result = service._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result is None

        def test__given_nyc_region__returns_pooled_cps(self):
            # Test with NYC region - should return pooled CPS dataset
            dataset = None
            country_id = "us"
            region = "nyc"

            # Create an instance of the class
            service = EconomyService()
            # Call the method
            result = service._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert (
                result == "gs://policyengine-us-data/pooled_3_year_cps_2023.h5"
            )

        def test__given_us_nationwide_dataset__returns_none(self):
            # Test with US nationwide dataset
            dataset = "us_nationwide"
            country_id = "us"
            region = "us"

            # Create an instance of the class
            service = EconomyService()
            # Call the method
            result = service._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result is None

        def test__given_uk_dataset__returns_none(self):
            # Test with UK dataset
            dataset = "uk_dataset"
            country_id = "uk"
            region = "country/england"

            # Create an instance of the class
            service = EconomyService()
            # Call the method
            result = service._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result is None
