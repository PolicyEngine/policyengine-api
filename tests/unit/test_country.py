import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from policyengine.countries.uk.regions import build_uk_region_registry
from policyengine.data.uk_geography_assets import packaged_uk_area_list_path
from policyengine_core.enums import EnumArray
from policyengine_core.model_api import Enum

from policyengine_api.country import (
    COUNTRIES,
    PolicyEngineCountry,
    _serialize_axis_result,
    get_requested_computations,
)

AREA_LIST_DIRECTORY = Path(__file__).parents[2] / "policyengine_api" / "data"
RECORDED_UK_REGION_OPTIONS_PATH = (
    Path(__file__).parents[1] / "data" / "uk_economy_region_options.json"
)


def _names_by_code(area_list: pd.DataFrame) -> dict[str, str]:
    return dict(zip(area_list["code"], area_list["name"], strict=True))


class ExampleEnum(Enum):
    FIRST = "First"
    SECOND = "Second"


class TestCountryJsonSafety:
    def test__json_safe_serializes_dates(self):
        country = PolicyEngineCountry.__new__(PolicyEngineCountry)

        result = country._json_safe(
            {
                "release_date": date(2026, 5, 12),
                "nested": [datetime(2026, 5, 12, 8, 30, 45)],
            }
        )

        assert result == {
            "release_date": "2026-05-12",
            "nested": ["2026-05-12T08:30:45"],
        }


class TestHouseholdCalculation:
    def test__calculate_does_not_enable_or_read_simulation_tracing(self, monkeypatch):
        class SimulationWithoutTracing:
            __slots__ = ()

            def calculate(self, variable_name, period):
                return np.array([40])

            def get_population(self, entity_plural):
                return SimpleNamespace(get_index=lambda _entity_id: 0)

        variable = SimpleNamespace(value_type=int)
        system = SimpleNamespace(
            variables={"age": variable},
            get_variable=lambda _variable_name: variable,
        )
        country = PolicyEngineCountry.__new__(PolicyEngineCountry)
        monkeypatch.setattr(
            country,
            "_create_simulation",
            lambda _household, _reform, **_kwargs: (SimulationWithoutTracing(), system),
        )

        result = country.calculate(
            {"people": {"you": {"age": {"2025": None}}}},
            None,
        )

        assert result.household["people"]["you"]["age"]["2025"] == 40


class TestAxisResults:
    @pytest.mark.parametrize(
        ("value_type", "values", "expected"),
        [
            (float, [1.5, np.inf, -np.inf], [1.5, "Infinity", "-Infinity"]),
            (int, [1, 2, 3], [1, 2, 3]),
            (bool, [True, False, True], [True, False, True]),
            (str, ["first", "second", "third"], ["first", "second", "third"]),
        ],
    )
    def test__serialize_axis_result_preserves_value_type(
        self,
        value_type,
        values,
        expected,
    ):
        variable = SimpleNamespace(value_type=value_type)
        result = np.array(values)

        assert _serialize_axis_result(result, variable, 0, 1) == expected

    def test__serialize_axis_result_decodes_enum_names(self):
        variable = SimpleNamespace(value_type=Enum)
        result = EnumArray(np.array([0, 1, 0]), ExampleEnum)

        assert _serialize_axis_result(result, variable, 0, 1) == [
            "FIRST",
            "SECOND",
            "FIRST",
        ]

    def test__axes_request_includes_provided_values_and_excludes_metadata(self):
        household = {
            "people": {
                "you": {
                    "age": {"2025": 40},
                    "employment_income": {"2025": None},
                }
            },
            "households": {"household": {"members": ["you"]}},
            "axes": [
                [
                    {
                        "name": "employment_income",
                        "period": "2025",
                        "min": 0,
                        "max": 40_000,
                        "count": 5,
                    }
                ]
            ],
        }

        computations = get_requested_computations(
            household,
            include_provided_values=True,
            variable_names={"age", "employment_income"},
        )

        assert set(computations) == {
            ("people", "you", "age", "2025"),
            ("people", "you", "employment_income", "2025"),
        }

    def test__ordinary_request_only_includes_null_values(self):
        household = {
            "people": {
                "you": {
                    "age": {"2025": 40},
                    "employment_income": {"2025": None},
                }
            }
        }

        assert get_requested_computations(household) == [
            ("people", "you", "employment_income", "2025")
        ]

    def test__axis_calculation_error_returns_null_array_and_warning(self, monkeypatch):
        class BrokenSimulation:
            __slots__ = ()

            def calculate(self, variable_name, period):
                msg = "calculation failed"
                raise RuntimeError(msg)

            def get_population(self, entity_plural):
                return SimpleNamespace(count=5)

        variable = SimpleNamespace(value_type=float)
        system = SimpleNamespace(
            variables={"employment_income": variable},
            get_variable=lambda _variable_name: variable,
        )
        country = PolicyEngineCountry.__new__(PolicyEngineCountry)
        monkeypatch.setattr(
            country,
            "_create_simulation",
            lambda _household, _reform, **_kwargs: (BrokenSimulation(), system),
        )
        household = {
            "people": {"you": {"employment_income": {"2025": None}}},
            "axes": [
                [
                    {
                        "name": "employment_income",
                        "period": "2025",
                        "min": 0,
                        "max": 40_000,
                        "count": 5,
                    }
                ]
            ],
        }

        result = country.calculate(household, None)

        assert (
            result.household["people"]["you"]["employment_income"]["2025"] == [None] * 5
        )
        assert result.warnings == (
            "Unable to calculate employment_income for you in 2025; "
            "returned 5 null axis values: calculation failed",
        )


class TestUKCountryMetadata:
    """Tests for UK country metadata, specifically local authority loading."""

    @pytest.fixture
    def uk_country(self):
        return COUNTRIES["uk"]

    @pytest.fixture
    def uk_regions(self, uk_country):
        return uk_country.metadata["economy_options"]["region"]

    def test__uk_metadata_contains_local_authorities(self, uk_regions):
        """Verify that local authorities are included in UK region options."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        assert len(local_authority_regions) > 0

    def test__uk_has_361_local_authorities(self, uk_regions):
        """Verify the correct number of local authorities are loaded."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        assert len(local_authority_regions) == 361

    def test__ards_and_north_down_is_offered(self, uk_regions):
        """The 11th Northern Ireland district (N09000011) is a selectable region."""
        assert {
            "name": "local_authority/Ards and North Down",
            "label": "Ards and North Down",
            "type": "local_authority",
        } in uk_regions

    def test__every_local_authority_resolves_in_the_policyengine_registry(
        self, uk_regions
    ):
        """Each offered name matches a .py registry label, ignoring case.

        The simulation API resolves ``local_authority/{name}`` to the registry
        code whose label matches the name, ignoring case.
        """
        registry = build_uk_region_registry(
            include_constituencies=False, include_local_authorities=True
        )
        registry_labels = {
            region.label.casefold(): region.code
            for region in registry.get_by_type("local_authority")
        }
        offered = [
            region["label"]
            for region in uk_regions
            if region.get("type") == "local_authority"
        ]
        assert [
            label for label in offered if label.casefold() not in registry_labels
        ] == []
        assert registry_labels["ards and north down"] == "local_authority/N09000011"

    def test__local_authority_regions_have_correct_name_format(self, uk_regions):
        """Verify local authority region names have the correct prefix."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        for region in local_authority_regions:
            assert region["name"].startswith("local_authority/")

    def test__local_authority_regions_have_labels(self, uk_regions):
        """Verify all local authority regions have labels."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        for region in local_authority_regions:
            assert "label" in region
            assert len(region["label"]) > 0

    def test__local_authority_regions_have_type_field(self, uk_regions):
        """Verify all local authority regions have type field set correctly."""
        local_authority_regions = [
            r for r in uk_regions if r.get("type") == "local_authority"
        ]
        for region in local_authority_regions:
            assert region["type"] == "local_authority"

    def test__specific_local_authorities_present(self, uk_regions):
        """Verify specific local authorities are present in metadata."""
        local_authority_names = [
            r["name"] for r in uk_regions if r.get("type") == "local_authority"
        ]
        # Check some well-known local authorities
        assert "local_authority/Hartlepool" in local_authority_names
        assert "local_authority/Middlesbrough" in local_authority_names
        assert "local_authority/Leicester" in local_authority_names

    def test__uk_still_has_constituencies(self, uk_regions):
        """Verify constituencies are still present after adding local authorities."""
        constituency_regions = [
            r for r in uk_regions if r.get("type") == "constituency"
        ]
        assert len(constituency_regions) == 650

    def test__uk_has_all_region_types(self, uk_regions):
        """Verify all expected region types are present."""
        types = {r.get("type") for r in uk_regions}
        assert "national" in types
        assert "country" in types
        assert "constituency" in types
        assert "local_authority" in types

    def test__uk_metadata_is_json_serializable(self, uk_country):
        """Verify metadata does not leak filesystem paths or other non-JSON values."""
        json.dumps(uk_country.metadata)

    def test__region_options_equal_the_recorded_list(self, uk_regions):
        """The region options equal the recorded list, entry by entry, in order.

        The recording holds the national entry, the four countries, the 650
        constituencies and the 361 local authorities, each with its name,
        label and type. A change to the packaged area lists, or to how they
        are read, must leave the offered regions as recorded.
        """
        recorded_regions = json.loads(
            RECORDED_UK_REGION_OPTIONS_PATH.read_text(encoding="utf-8")
        )

        assert Counter(region["type"] for region in recorded_regions) == {
            "national": 1,
            "country": 4,
            "constituency": 650,
            "local_authority": 361,
        }
        assert uk_regions == recorded_regions


class TestLocalAuthoritiesDataFile:
    """Tests for the local authorities CSV data file."""

    @pytest.fixture
    def local_authorities_df(self):
        return pd.read_csv(AREA_LIST_DIRECTORY / "local_authorities_2021.csv")

    def test__file_has_only_code_and_name_columns(self, local_authorities_df):
        """The file holds each authority's code and name, and no hex-map position."""
        assert list(local_authorities_df.columns) == ["code", "name"]

    def test__file_has_361_local_authorities(self, local_authorities_df):
        """Verify the correct number of local authorities in file."""
        assert len(local_authorities_df) == 361

    def test__file_matches_the_installed_policyengine_list(self, local_authorities_df):
        """Codes and names equal .py's packaged 2023 list.

        .py's list is read from the installed package, so a .py update that
        changes a code or a name makes this test fail until the file follows.
        """
        policyengine_list = pd.read_csv(packaged_uk_area_list_path("local_authority"))

        assert _names_by_code(local_authorities_df) == _names_by_code(policyengine_list)

    def test__all_codes_are_valid_ons_codes(self, local_authorities_df):
        """Verify all codes follow ONS local authority code patterns."""
        for code in local_authorities_df["code"]:
            # ONS codes start with E (England), S (Scotland), W (Wales), or N
            # (Northern Ireland)
            assert code[0] in ["E", "S", "W", "N"]

    def test__all_names_are_non_empty(self, local_authorities_df):
        """Verify all local authority names are non-empty."""
        for name in local_authorities_df["name"]:
            assert len(str(name)) > 0

    def test__english_local_authorities_have_e_prefix(self, local_authorities_df):
        """Verify English local authorities have E prefix codes."""
        english_las = local_authorities_df[
            local_authorities_df["code"].str.startswith("E")
        ]
        # England has 296 local authorities (majority of the 361 total)
        assert len(english_las) == 296

    def test__scottish_local_authorities_have_s_prefix(self, local_authorities_df):
        """Verify Scottish local authorities have S prefix codes."""
        scottish_las = local_authorities_df[
            local_authorities_df["code"].str.startswith("S")
        ]
        # Scotland has 32 council areas
        assert len(scottish_las) == 32

    def test__welsh_local_authorities_have_w_prefix(self, local_authorities_df):
        """Verify Welsh local authorities have W prefix codes."""
        welsh_las = local_authorities_df[
            local_authorities_df["code"].str.startswith("W")
        ]
        # Wales has 22 principal areas
        assert len(welsh_las) == 22

    def test__northern_irish_local_authorities_have_n_prefix(
        self, local_authorities_df
    ):
        """Verify all 11 Northern Ireland districts have N prefix codes."""
        northern_irish_las = local_authorities_df[
            local_authorities_df["code"].str.startswith("N")
        ]
        assert len(northern_irish_las) == 11
        assert "N09000011" in set(northern_irish_las["code"])


class TestConstituenciesDataFile:
    """Tests for the 2024 constituencies CSV data file."""

    @pytest.fixture
    def constituencies_df(self):
        return pd.read_csv(AREA_LIST_DIRECTORY / "constituencies_2024.csv")

    def test__file_has_only_code_and_name_columns(self, constituencies_df):
        """The file holds each constituency's code and name, and no hex-map position."""
        assert list(constituencies_df.columns) == ["code", "name"]

    def test__file_has_650_constituencies(self, constituencies_df):
        assert len(constituencies_df) == 650

    def test__file_matches_the_installed_policyengine_list(self, constituencies_df):
        """Codes and names equal .py's packaged 2024 constituency list.

        .py's list is read from the installed package, so a .py update that
        changes a code or a name makes this test fail until the file follows.
        """
        policyengine_list = pd.read_csv(packaged_uk_area_list_path("constituency"))

        assert _names_by_code(constituencies_df) == _names_by_code(policyengine_list)


class TestSimulationCompatibility:
    def test__create_simulation_uses_legacy_tax_benefit_system_signature(self):
        class LegacySimulation:
            def __init__(self, *, tax_benefit_system, situation):
                self.tax_benefit_system = tax_benefit_system
                self.situation = situation

        country = PolicyEngineCountry.__new__(PolicyEngineCountry)
        country.country_package = SimpleNamespace(Simulation=LegacySimulation)
        country.tax_benefit_system = object()

        simulation, system = country._create_simulation(
            {"households": {"household": {}}},
            None,
        )

        assert system is country.tax_benefit_system
        assert simulation.tax_benefit_system is country.tax_benefit_system
        assert simulation.situation == {"households": {"household": {}}}

    def test__create_simulation_uses_reform_signature_when_system_arg_is_unsupported(
        self,
    ):
        class ModernSimulation:
            def __init__(self, *, situation, reform=None):
                self.situation = situation
                self.reform = reform
                self.tax_benefit_system = "modern-system"

        country = PolicyEngineCountry.__new__(PolicyEngineCountry)
        country.country_package = SimpleNamespace(Simulation=ModernSimulation)
        country.tax_benefit_system = object()

        simulation, system = country._create_simulation(
            {"households": {"household": {}}},
            None,
        )

        assert system == "modern-system"
        assert simulation.tax_benefit_system == "modern-system"
        assert simulation.reform is None
        assert simulation.situation == {"households": {"household": {}}}
