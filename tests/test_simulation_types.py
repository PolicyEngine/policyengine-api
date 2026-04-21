"""Tests for the api-local simulation-types module.

These types replace the pre-v4 ``policyengine.simulation.SimulationOptions``
and ``policyengine.utils.data.datasets.get_default_dataset`` imports.
They are api-owned so the api can evolve its dep on pe.py without
breaking the Modal simulation-worker wire contract.
"""

import pytest

from policyengine_api.libs.simulation_types import (
    SimulationOptions,
    get_default_dataset,
)


class TestSimulationOptions:
    def test_minimal_payload_roundtrips(self):
        options = SimulationOptions(
            country="us",
            scope="macro",
            reform={},
            baseline={},
            time_period="2024",
            region="us",
            data="hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5",
        )
        payload = options.model_dump(mode="json")
        assert payload["country"] == "us"
        assert payload["scope"] == "macro"
        assert payload["include_cliffs"] is False
        assert payload["model_version"] is None
        assert payload["data_version"] is None

    def test_reform_and_baseline_are_opaque_dicts(self):
        reform = {
            "gov.irs.credits.eitc.max": {"2024-01-01.2024-12-31": {"value": 4000}}
        }
        baseline = {}
        options = SimulationOptions(
            country="us",
            scope="macro",
            reform=reform,
            baseline=baseline,
            time_period="2024",
            region="us",
            data="hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5",
        )
        assert options.reform == reform

    def test_scope_is_restricted_to_macro_or_household(self):
        with pytest.raises(Exception):
            SimulationOptions(
                country="us",
                scope="invalid-scope",  # type: ignore[arg-type]
                reform={},
                baseline={},
                time_period="2024",
                region="us",
                data="default",
            )

    def test_version_pins_surface_in_payload(self):
        options = SimulationOptions(
            country="us",
            scope="macro",
            reform={},
            baseline={},
            time_period="2024",
            include_cliffs=True,
            region="state/CA",
            data="hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5",
            model_version="1.653.3",
            data_version="1.85.2",
        )
        payload = options.model_dump(mode="json")
        assert payload["model_version"] == "1.653.3"
        assert payload["data_version"] == "1.85.2"
        assert payload["include_cliffs"] is True
        assert payload["region"] == "state/CA"


class TestGetDefaultDataset:
    def test_us_national_returns_enhanced_cps_hf_uri(self):
        assert (
            get_default_dataset("us", "us")
            == "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5"
        )

    def test_uk_national_returns_uk_hf_uri(self):
        assert (
            get_default_dataset("uk", "uk")
            == "hf://policyengine/policyengine-uk-data/enhanced_frs_2022_23.h5"
        )

    def test_us_state_region_falls_back_to_national_default(self):
        assert get_default_dataset("us", "state/CA") == get_default_dataset("us", "us")

    def test_us_district_region_falls_back_to_national_default(self):
        assert get_default_dataset(
            "us", "congressional_district/CA-12"
        ) == get_default_dataset("us", "us")

    def test_unknown_country_raises(self):
        with pytest.raises(ValueError, match="country_id='lu'"):
            get_default_dataset("lu", "lu")
