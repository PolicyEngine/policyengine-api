import json
from collections import Counter
from datetime import date, datetime
from importlib.metadata import distribution
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from policyengine.countries.uk.regions import build_uk_region_registry
from policyengine_core.enums import EnumArray
from policyengine_core.model_api import Enum

from policyengine_api.country import (
    COUNTRIES,
    PolicyEngineCountry,
    _serialize_axis_result,
    get_requested_computations,
)

RECORDED_UK_REGION_OPTIONS_PATH = (
    Path(__file__).parents[1] / "data" / "uk_economy_region_options.json"
)
UK_AREA_TYPES = ("constituency", "local_authority")


class _InstalledWheelStandIn:
    """Stands in for an installed wheel whose files are under ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def locate_file(self, path: str) -> Path:
        return self.root / path


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


UK_DATASET_DATA_YEAR = 2024


def uk_model_projected_years(data_year):
    """Return the years policyengine-uk's own projection gives a dataset.

    Projects a three-household dataset of ``data_year`` with the installed
    model, as the simulation service's model projects the UK dataset.
    """
    from policyengine_uk.data.dataset_schema import UKSingleYearDataset
    from policyengine_uk.data.economic_assumptions import extend_single_year_dataset
    from policyengine_uk.system import system

    household_ids = np.arange(1, 4)
    dataset = UKSingleYearDataset(
        person=pd.DataFrame(
            {
                "person_id": household_ids,
                "person_benunit_id": household_ids,
                "person_household_id": household_ids,
                "age": [45, 30, 70],
            }
        ),
        benunit=pd.DataFrame({"benunit_id": household_ids}),
        household=pd.DataFrame(
            {
                "household_id": household_ids,
                "household_weight": [2.0, 3.0, 5.0],
                "region": "LONDON",
                "tenure_type": "OWNED_OUTRIGHT",
                "rent": 0.0,
                "council_tax": 0.0,
            }
        ),
        fiscal_year=data_year,
    )
    projected = extend_single_year_dataset(dataset, system.parameters)
    return sorted(int(year) for year in projected.years)


class TestUKCountryMetadata:
    """Tests for UK country metadata, specifically its region options."""

    @pytest.fixture
    def uk_country(self):
        return COUNTRIES["uk"]

    @pytest.fixture
    def uk_regions(self, uk_country):
        return uk_country.metadata["economy_options"]["region"]

    def test__uk_years_run_to_the_models_last_projected_year(self, uk_country):
        """The UK years end where the installed policyengine-uk projects its data.

        The simulation service refuses a later year (DATASET_YEAR_UNAVAILABLE),
        and the app offers no year after the last one listed here.
        """
        years = [
            period["name"]
            for period in uk_country.metadata["economy_options"]["time_period"]
        ]
        projected_years = uk_model_projected_years(UK_DATASET_DATA_YEAR)

        assert years == projected_years
        assert [
            period["label"]
            for period in uk_country.metadata["economy_options"]["time_period"]
        ] == [str(year) for year in projected_years]

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

    def test__area_regions_equal_the_policyengine_registry(self, uk_regions):
        """The constituency and local-authority options are .py's registry areas.

        Each option's name is ``<type>/<label>`` and its label is the registry
        label, with each type's areas sorted by label. The simulation API
        resolves ``<type>/<label>`` to the registry code with that label.
        """
        registry = build_uk_region_registry(
            include_constituencies=True, include_local_authorities=True
        )
        registry_areas = [
            {"name": f"{area_type}/{label}", "label": label, "type": area_type}
            for area_type in UK_AREA_TYPES
            for label in sorted(
                region.label for region in registry.get_by_type(area_type)
            )
        ]

        offered_areas = [
            region for region in uk_regions if region["type"] in UK_AREA_TYPES
        ]

        assert len(offered_areas) == 650 + 361
        assert offered_areas == registry_areas

    def test__area_regions_follow_the_installed_policyengine_area_lists(
        self, uk_country, monkeypatch, tmp_path
    ):
        """The area options come from the area lists in the installed .py wheel.

        A stand-in wheel lists two areas of each type, out of name order. The
        options offer exactly those areas, sorted by name.
        """
        area_list_directory = tmp_path / "policyengine" / "data" / "uk_geography"
        area_list_directory.mkdir(parents=True)
        (area_list_directory / "constituencies_2024.csv").write_text(
            "code,name,x,y\n"
            "E14999998,Zeta Test Constituency,1,2\n"
            "E14999999,Alpha Test Constituency,3,4\n",
            encoding="utf-8",
        )
        (area_list_directory / "local_authorities_2023.csv").write_text(
            "code,name,x,y\n"
            "E06999998,Zeta Test Authority,1,2\n"
            'E06999999,"Alpha Test Authority, City of",3,4\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "policyengine_api.constants.distribution",
            lambda name: (
                _InstalledWheelStandIn(tmp_path)
                if name == "policyengine"
                else distribution(name)
            ),
        )

        area_options = [
            region
            for region in uk_country.build_microsimulation_options()["region"]
            if region["type"] in UK_AREA_TYPES
        ]

        assert area_options == [
            {
                "name": "constituency/Alpha Test Constituency",
                "label": "Alpha Test Constituency",
                "type": "constituency",
            },
            {
                "name": "constituency/Zeta Test Constituency",
                "label": "Zeta Test Constituency",
                "type": "constituency",
            },
            {
                "name": "local_authority/Alpha Test Authority, City of",
                "label": "Alpha Test Authority, City of",
                "type": "local_authority",
            },
            {
                "name": "local_authority/Zeta Test Authority",
                "label": "Zeta Test Authority",
                "type": "local_authority",
            },
        ]

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
