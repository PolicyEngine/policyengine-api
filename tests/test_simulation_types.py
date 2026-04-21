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
    def test_us_national_returns_enhanced_cps_gcs_uri(self):
        assert (
            get_default_dataset("us", "us")
            == "gs://policyengine-us-data/enhanced_cps_2024.h5"
        )

    def test_uk_national_returns_private_frs_gcs_uri(self):
        # UK h5 lives in the ``-private`` bucket because the underlying
        # FRS microdata is UKDS-licensed and cannot be redistributed
        # through the public bucket. The Modal worker has access.
        assert (
            get_default_dataset("uk", "uk")
            == "gs://policyengine-uk-data-private/enhanced_frs_2023_24.h5"
        )

    def test_us_state_has_its_own_h5(self):
        # Pre-v4 contract: state regions have per-state h5 files, not a
        # national fallback. Case-normalized to uppercase.
        assert (
            get_default_dataset("us", "state/ca")
            == "gs://policyengine-us-data/states/CA.h5"
        )
        assert (
            get_default_dataset("us", "state/UT")
            == "gs://policyengine-us-data/states/UT.h5"
        )

    def test_us_congressional_district_has_its_own_h5(self):
        assert (
            get_default_dataset("us", "congressional_district/CA-37")
            == "gs://policyengine-us-data/districts/CA-37.h5"
        )

    def test_us_place_reuses_parent_state_h5(self):
        assert (
            get_default_dataset("us", "place/NJ-57000")
            == "gs://policyengine-us-data/states/NJ.h5"
        )

    def test_unknown_us_region_raises(self):
        with pytest.raises(ValueError, match="Unknown US region"):
            get_default_dataset("us", "not-a-region")

    def test_unknown_country_raises(self):
        with pytest.raises(ValueError, match="country_id='lu'"):
            get_default_dataset("lu", "lu")
