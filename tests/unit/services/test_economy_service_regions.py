"""Region validation and the region codes sent to the simulation API."""

import pytest

from policyengine_api.services.economy_service import EconomyService

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomicImpactSetupOptions:
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

        @pytest.mark.parametrize(
            "region",
            [
                "uk",
                "country/england",
                "country/scotland",
                "country/wales",
                "country/northern_ireland",
                "constituency/Aldershot",
            ],
        )
        def test__given_other_uk_region__returns_unchanged(self, region):
            assert EconomyService()._setup_region("uk", region) == region

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
            with pytest.raises(ValueError, match="Invalid US state: 'mb'"):
                service._setup_region("us", "state/mb")

        def test__given_invalid_congressional_district__raises_value_error(
            self,
        ):
            service = EconomyService()
            with pytest.raises(
                ValueError, match="Invalid congressional district: 'cruft'"
            ):
                service._setup_region("us", "congressional_district/cruft")

        def test__given_invalid_prefix__raises_value_error(self):
            service = EconomyService()
            with pytest.raises(
                ValueError, match="Invalid US region: 'invalid_prefix/tx'"
            ):
                service._setup_region("us", "invalid_prefix/tx")

        def test__given_invalid_bare_value__raises_value_error(self):
            # Bare values without prefix are now invalid (should be normalized first)
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid US region: 'invalid_value'"):
                service._setup_region("us", "invalid_value")

        def test__given_place_region__returns_unchanged(self):
            # Test normalized "place/STATE-FIPS" format passes through
            service = EconomyService()
            result = service._setup_region("us", "place/NJ-57000")
            assert result == "place/NJ-57000"

        def test__given_invalid_place_format__raises_value_error(self):
            # Test place without hyphen raises error
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid place format"):
                service._setup_region("us", "place/invalid")

        def test__given_invalid_place_state__raises_value_error(self):
            # Test place with invalid state code raises error
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid state in place code"):
                service._setup_region("us", "place/XX-57000")

        def test__given_invalid_place_fips__raises_value_error(self):
            # Test place with invalid FIPS code raises error
            service = EconomyService()
            with pytest.raises(ValueError, match="Invalid FIPS code"):
                service._setup_region("us", "place/NJ-abc")

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
            with pytest.raises(ValueError, match="Invalid US state: 'mb'"):
                service._validate_us_region("state/mb")

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
            with pytest.raises(
                ValueError, match="Invalid congressional district: 'CA-99'"
            ):
                service._validate_us_region("congressional_district/CA-99")

        def test__given_nonexistent_district__raises_value_error(self):
            service = EconomyService()
            with pytest.raises(
                ValueError, match="Invalid congressional district: 'cruft'"
            ):
                service._validate_us_region("congressional_district/cruft")
