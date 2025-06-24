import json

from policyengine_api.jobs.calculate_economy_simulation_job import (
    CalculateEconomySimulationJob,
    SimulationAPI,
)
from typing import Literal


class TestSimulationAPI:
    class TestSetupSimOptions:
        test_country_id = "us"
        test_reform_policy = json.dumps(
            {"sample_param": {"2024-01-01.2100-12-31": 15}}
        )
        test_current_law_baseline_policy = json.dumps({})
        test_region = "us"
        test_dataset = None
        test_time_period = "2025"
        test_scope: Literal["macro"] = "macro"

        def test__given_valid_options__returns_correct_sim_options(self):

            # Create an instance of the class
            sim_api = SimulationAPI()

            # Call the method with the test data; patch setup_region and setup_data methods
            sim_options = sim_api._setup_sim_options(
                self.test_country_id,
                self.test_reform_policy,
                self.test_current_law_baseline_policy,
                self.test_region,
                self.test_dataset,
                self.test_time_period,
                self.test_scope,
            )

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
            time_period = "2025"
            scope = "macro"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            sim_options = sim_api._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                dataset,
                time_period,
                scope,
            )
            # Assert the expected values in the returned dictionary
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(
                current_law_baseline_policy
            )
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ca"
            assert (
                sim_options["data"]
                == "gs://policyengine-us-data/pooled_3_year_cps_2023.h5"
            )

        def test__given_enhanced_cps_state__returns_correct_sim_options(self):
            # Test with enhanced_cps dataset
            country_id = "us"
            reform_policy = json.dumps(
                {"sample_param": {"2024-01-01.2100-12-31": 15}}
            )
            current_law_baseline_policy = json.dumps({})
            region = "ut"
            dataset = "enhanced_cps"
            time_period = "2025"
            scope = "macro"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            sim_options = sim_api._setup_sim_options(
                country_id,
                reform_policy,
                current_law_baseline_policy,
                region,
                dataset,
                time_period,
                scope,
            )
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
            time_period = "2025"
            scope = "macro"
            target = "cliff"

            # Create an instance of the class
            sim_api = SimulationAPI()

            # Call the method
            sim_options = sim_api._setup_sim_options(
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
            sim_api = SimulationAPI()

            # Call the method
            result = sim_api._setup_region(country_id, region)
            # Assert the expected value
            assert result == "state/ca"

        def test__given_non_us_state__returns_correct_region(self):
            # Test with non-US region
            country_id = "uk"
            region = "country/england"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_region(country_id, region)
            # Assert the expected value
            assert result == region

    class TestSetupData:
        def test__given_enhanced_cps_dataset__returns_correct_gcp_path(self):
            # Test with enhanced_cps dataset
            dataset = "enhanced_cps"
            country_id = "us"
            region = "us"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result == "gs://policyengine-us-data/enhanced_cps_2024.h5"

        def test__given_us_state_dataset__returns_correct_gcp_path(self):
            # Test with US state dataset
            dataset = "us_state"
            country_id = "us"
            region = "ca"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_data(dataset, country_id, region)
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
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result is None

        def test__given_uk_dataset__returns_none(self):
            # Test with UK dataset
            dataset = "uk_dataset"
            country_id = "uk"
            region = "country/england"

            # Create an instance of the class
            sim_api = SimulationAPI()
            # Call the method
            result = sim_api._setup_data(dataset, country_id, region)
            # Assert the expected value
            assert result is None


class TestSetJobId:
    def test__sets_job_id(self):

        job = object.__new__(CalculateEconomySimulationJob)
        job_id = job._set_job_id()

        assert isinstance(job_id, str)
