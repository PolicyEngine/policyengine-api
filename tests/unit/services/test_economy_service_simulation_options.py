"""Simulation API options built from resolved setup options."""

import json
from dataclasses import replace
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_service import EconomyService
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_POLICY_ID,
    MOCK_TIME_PERIOD,
)
from tests.fixtures.services.economy_service_helpers import (
    setup_options_for,
    uk_breakdown_request,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomicImpactSetupOptions:
    class TestSetupSimOptions:
        """Tests for _setup_sim_options method.

        Note: _setup_sim_options now expects pre-normalized regions and returns
        no concrete data field for default datasets. The simulation gateway
        resolves the certified dataset from the requested .py bundle.
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
                setup_options_for(self.test_country_id, self.test_region),
                reform_policy=self.test_reform_policy,
                baseline_policy=self.test_current_law_baseline_policy,
                time_period=self.test_time_period,
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
            assert "data" not in sim_options

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
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
            )
            sim_options = sim_options_model.model_dump()

            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ca"
            assert "data" not in sim_options

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
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
            )
            sim_options = sim_options_model.model_dump()

            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == "state/ut"
            assert "data" not in sim_options

        def test__given_cliff_target__returns_correct_sim_options(self):
            country_id = "us"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "us"
            time_period = 2025
            scope = "macro"

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
                include_cliffs=True,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["country"] == country_id
            assert sim_options["scope"] == scope
            assert sim_options["reform"] == json.loads(reform_policy)
            assert sim_options["baseline"] == json.loads(current_law_baseline_policy)
            assert sim_options["time_period"] == time_period
            assert sim_options["region"] == region
            assert "data" not in sim_options
            assert sim_options["include_cliffs"] is True

        def test__given_uk__returns_correct_sim_options(self):
            country_id = "uk"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "uk"
            time_period = 2025

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["country"] == country_id
            assert sim_options["region"] == region
            assert "data" not in sim_options

        def test__given_congressional_district__returns_correct_sim_options(
            self,
        ):
            country_id = "us"
            reform_policy = json.dumps({"sample_param": {"2024-01-01.2100-12-31": 15}})
            current_law_baseline_policy = json.dumps({})
            region = "congressional_district/CA-37"  # Pre-normalized
            time_period = 2025

            service = EconomyService()

            sim_options_model = service._setup_sim_options(
                setup_options_for(country_id, region),
                reform_policy=reform_policy,
                baseline_policy=current_law_baseline_policy,
                time_period=time_period,
            )

            sim_options = sim_options_model.model_dump()
            assert sim_options["region"] == "congressional_district/CA-37"
            assert "data" not in sim_options

        def test__given_local_area_breakdown__sends_breakdown(self):
            setup_options = setup_options_for("uk", "country/scotland")
            setup_options.options = {"breakdown": "local_areas"}

            sim_options = (
                EconomyService()
                ._setup_sim_options(
                    setup_options,
                    reform_policy=self.test_reform_policy,
                    baseline_policy=self.test_current_law_baseline_policy,
                    time_period=2026,
                )
                .model_dump(mode="json")
            )

            assert sim_options["breakdown"] == "local_areas"
            assert sim_options["region"] == "country/scotland"

        @pytest.mark.parametrize("mode", ["python", "json"])
        def test__given_no_breakdown__sends_no_breakdown_field(self, mode):
            sim_options = (
                EconomyService()
                ._setup_sim_options(
                    setup_options_for("uk", "uk"),
                    reform_policy=self.test_reform_policy,
                    baseline_policy=self.test_current_law_baseline_policy,
                    time_period=2026,
                )
                .model_dump(mode=mode)
            )

            assert "breakdown" not in sim_options

        def test__given_uk_northern_ireland__sends_the_registry_code(self):
            setup_options = setup_options_for("uk", "country/northern_ireland")

            sim_options = EconomyService()._setup_sim_options(
                setup_options,
                reform_policy=self.test_reform_policy,
                baseline_policy=self.test_current_law_baseline_policy,
                time_period=2026,
            )

            assert sim_options.region == "country/northern_ireland"
            assert setup_options.region == "country/northern_ireland"

    class TestDatasetSelection:
        @pytest.mark.parametrize(
            "dataset",
            ["populace_us_2024", "enhanced_cps", "hf://example/data.h5"],
        )
        def test__given_custom_dataset__rejects_it(self, dataset):
            service = EconomyService()
            with pytest.raises(ValueError, match="Custom datasets are not supported"):
                service._build_economic_impact_setup_options(
                    EconomicImpactRequest(
                        country_id="us",
                        policy_id=MOCK_POLICY_ID,
                        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                        region="us",
                        dataset=dataset,
                        options={},
                        api_version=MOCK_API_VERSION,
                    ),
                    time_period=MOCK_TIME_PERIOD,
                )

    class TestLocalAreaBreakdownSelection:
        @pytest.mark.parametrize(
            "region",
            [
                "uk",
                "country/england",
                "country/scotland",
                "country/wales",
                "country/northern_ireland",
            ],
        )
        def test__given_uk_or_uk_country__accepts_breakdown(self, region):
            gateway = MagicMock()

            setup_options = EconomyService(
                simulation_entrypoint_=gateway
            )._build_economic_impact_setup_options(
                uk_breakdown_request(region=region), time_period=MOCK_TIME_PERIOD
            )

            assert setup_options.options == {"breakdown": "local_areas"}
            assert setup_options.region == region
            assert setup_options.options_hash.startswith(
                "[breakdown=local_areas&dataset=default&"
            )

        @pytest.mark.parametrize(
            ("country_id", "region", "target", "message"),
            [
                ("us", "us", "general", "only available for UK"),
                ("us", "state/ca", "general", "only available for UK"),
                (
                    "uk",
                    "constituency/Aldershot",
                    "general",
                    "region uk or a UK country",
                ),
                (
                    "uk",
                    "local_authority/E07000092",
                    "general",
                    "region uk or a UK country",
                ),
                ("uk", "scotland", "general", "region uk or a UK country"),
                ("uk", "country/", "general", "region uk or a UK country"),
                # A query value of country/%20 reaches the service decoded.
                ("uk", "country/ ", "general", "region uk or a UK country"),
                ("uk", "country/%20", "general", "region uk or a UK country"),
                ("uk", "country/NI", "general", "region uk or a UK country"),
                ("uk", "country/ni", "general", "region uk or a UK country"),
                ("uk", "country/france", "general", "region uk or a UK country"),
                ("uk", "Country/scotland", "general", "region uk or a UK country"),
                ("uk", "country/scotland ", "general", "region uk or a UK country"),
                ("uk", "UK", "general", "region uk or a UK country"),
                ("uk", " uk", "general", "region uk or a UK country"),
                ("uk", "uk", "cliff", "target=cliff"),
                ("uk", "country/wales", "cliff", "target=cliff"),
            ],
        )
        def test__given_unsupported_request__rejects_breakdown(
            self, country_id, region, target, message
        ):
            gateway = MagicMock()

            with (
                patch(
                    "policyengine_api.services.economy_service."
                    "get_economy_impact_cache_version"
                ) as cache_version,
                pytest.raises(ValueError, match=message),
            ):
                EconomyService(
                    simulation_entrypoint_=gateway
                )._build_economic_impact_setup_options(
                    uk_breakdown_request(
                        country_id=country_id, region=region, target=target
                    ),
                    time_period=MOCK_TIME_PERIOD,
                )

            # Every case is rejected before the cache identity is built.
            cache_version.assert_not_called()
            assert gateway.mock_calls == []
            if country_id == "us":
                # Only a US request reaches the worker's SPM capability check,
                # which runs right after this one: a UK request has no SPM
                # selection, so it would never fetch the capability anyway.
                gateway.get_spm_capability.assert_not_called()

        def test__given_unsupported_region__names_every_accepted_region(self):
            with pytest.raises(ValueError, match="breakdown=local_areas") as raised:
                EconomyService(
                    simulation_entrypoint_=MagicMock()
                )._build_economic_impact_setup_options(
                    uk_breakdown_request(region="country/france"),
                    time_period=MOCK_TIME_PERIOD,
                )

            assert str(raised.value) == (
                "breakdown=local_areas needs region uk or a UK country, one of "
                "uk, country/england, country/scotland, country/wales, "
                "country/northern_ireland; not 'country/france'"
            )

        def test__given_unknown_breakdown_option__rejects_it(self):
            request = replace(
                uk_breakdown_request(), options={"breakdown": "constituencies"}
            )

            with pytest.raises(ValueError, match="Unknown breakdown: 'constituencies'"):
                EconomyService(
                    simulation_entrypoint_=MagicMock()
                )._build_economic_impact_setup_options(
                    request, time_period=MOCK_TIME_PERIOD
                )
