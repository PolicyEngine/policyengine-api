"""Exercise the API country adapter's SPM handling over stand-in simulations.

Nothing here loads the US model or its SPM forecast: each stand-in raises the
error, or reports the receipt, the installed model does for that case, and the
tests check what the API makes of it. Two checks against the installed model
are in tests/integration/test_installed_us_model_spm.py.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest
from flask import Flask

from policyengine_api import country as country_module
from policyengine_api import spm
from policyengine_api.country import PolicyEngineCountry
from policyengine_api.data.v1_models import Policy
from policyengine_api.extensions import cache
from policyengine_api.routes import household_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_calculations import (
    HouseholdCalculationCache,
)
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
)
from policyengine_api.services.household_service import HouseholdService

AXIS_POINTS = 2
SPM_INPUT_MESSAGE = "Missing or unavailable explicit SPM input"
# What a stand-in simulation calculates for every variable it does not refuse.
CALCULATED_VALUE = 1234.0
# The stand-in bundle's forecast, and the one metro area that forecast has.
FORECAST_SHA256 = "a" * 64
STAND_IN_AREA = "test-area"
STAND_IN_RUNTIME_VERSIONS = {
    "policyengine": "test",
    "policyengine-core": "test",
    "policyengine-us": "test",
    "spm-calculator": "test",
}
CURRENT_LAW_POLICY_ID = 2


def _yearly_variable(name, entity, *, default=None):
    """Describe a yearly variable as country metadata does; a default makes an input."""
    return {
        "name": name,
        "entity": entity,
        "definitionPeriod": "year",
        "isInputVariable": default is not None,
        "defaultValue": default,
    }


# The metadata the household routes validate and complete a household against.
STAND_IN_METADATA = {
    "variables": {
        variable["name"]: variable
        for variable in (
            _yearly_variable("age", "person", default=0),
            _yearly_variable("employment_income", "person", default=0),
            _yearly_variable("state_code", "household", default="CA"),
            _yearly_variable("county_fips", "household", default=""),
            _yearly_variable("spm_unit_federal_tax", "spm_unit"),
            _yearly_variable("spm_unit_net_income", "spm_unit"),
            _yearly_variable("spm_unit_spm_threshold", "spm_unit"),
        )
    },
    "entities": {
        "person": {"plural": "people", "roles": {}},
        "household": {
            "plural": "households",
            "roles": {"member": {"plural": "members"}},
        },
        "spm_unit": {"plural": "spm_units", "roles": {"member": {"plural": "members"}}},
    },
    "parameters": {},
}
# An axes request expands every recognized variable, so a stub system must name
# the ones these households carry; anything else (entity membership) is skipped.
HOUSEHOLD_VARIABLES = frozenset(STAND_IN_METADATA["variables"])


def requested_household(variable="spm_unit_spm_threshold", *, axes=False, year="2024"):
    household = {
        "people": {"you": {"age": {year: 40}}},
        "households": {"household": {"members": ["you"], "state_code": {year: "CA"}}},
        "spm_units": {"spm_unit": {"members": ["you"], variable: {year: None}}},
    }
    if axes:
        household["axes"] = [
            [
                {
                    "name": "employment_income",
                    "period": year,
                    "count": AXIS_POINTS,
                    "min": 0,
                    "max": 100,
                }
            ]
        ]
    return household


def _country_raising(monkeypatch, error):
    """Return a country whose every variable calculation raises `error`."""

    def calculate(_variable, _period):
        # This also represents a requested resource with a nested SPM dependency.
        raise error

    simulation = SimpleNamespace(
        calculate=calculate,
        get_population=lambda _entity: SimpleNamespace(
            get_index=lambda _entity_id: 0, count=AXIS_POINTS
        ),
    )
    system = SimpleNamespace(
        get_variable=lambda _name: object(), variables=HOUSEHOLD_VARIABLES
    )
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    monkeypatch.setattr(
        country, "_create_simulation", lambda *_args, **_kwargs: (simulation, system)
    )
    return country


def _spm_input_error(code, message=SPM_INPUT_MESSAGE):
    """Return the typed ValueError a country raises for a missing input."""
    error = ValueError(message)
    error.code = code
    return error


def _failing_country(monkeypatch, code):
    error = _spm_input_error(code)
    return _country_raising(monkeypatch, error), error


def country_receipt(selection, years=()):
    """Return the rich receipt a country reports for `selection` over `years`."""
    return {
        "forecast_id": "test-artifact",
        "forecast_sha256": selection["forecast_content_sha256"],
        "scenario": selection["scenario"],
        "geography_kind": selection["geography_kind"],
        "runtime_versions": STAND_IN_RUNTIME_VERSIONS,
        "years": {year: {} for year in years},
        "geographies": [],
        "composition_method": "test adult classification",
        "storage_method": "test final cast",
    }


@pytest.mark.parametrize("code", sorted(spm.SPM_INPUT_ERROR_CODES))
@pytest.mark.parametrize("axes", [False, True])
def test_country_never_swallows_spm_input_errors_for_a_chosen_measurement(
    monkeypatch, code, axes
):
    country, error = _failing_country(monkeypatch, code)
    with pytest.raises(
        ValueError, match="Missing or unavailable explicit SPM input"
    ) as caught:
        country.calculate(
            requested_household("spm_unit_net_income", axes=axes),
            None,
            spm_requested=True,
        )
    assert caught.value is error


@pytest.mark.parametrize("code", sorted(spm.SPM_INPUT_ERROR_CODES))
@pytest.mark.parametrize("axes", [False, True])
def test_inherited_measurement_leaves_dependent_variables_unavailable(
    monkeypatch, code, axes
):
    """Leave variables that depend on an inherited SPM measurement null.

    Nobody chose this measurement, so its dependants behave like any other
    variable the model cannot compute: null, not a rejected request.
    """
    country, _ = _failing_country(monkeypatch, code)
    # The requested cell is seeded null, so returning at all is the observable
    # change; the sibling test below pins that the rest of the result survives.
    result = country.calculate(
        requested_household("spm_unit_net_income", axes=axes), None
    )
    unavailable = result.household["spm_units"]["spm_unit"]["spm_unit_net_income"][
        "2024"
    ]
    # An axes request spells one unavailable cell as a correctly sized null array.
    assert unavailable == ([None] * AXIS_POINTS if axes else None)
    assert any("spm_unit_net_income" in warning for warning in result.warnings) is axes


def test_an_inherited_measurement_still_returns_the_rest_of_the_calculation(
    monkeypatch,
):
    """A missing primitive costs its dependants, not the whole calculation."""
    error = ValueError("Missing or unavailable explicit SPM input")
    error.code = "SPM_GEOGRAPHY_REQUIRED"

    def calculate(variable, _period):
        if variable == "spm_unit_net_income":
            raise error
        return np.array([1234.0])

    simulation = SimpleNamespace(
        calculate=calculate,
        get_population=lambda _entity: SimpleNamespace(get_index=lambda _entity_id: 0),
    )
    system = SimpleNamespace(
        get_variable=lambda _name: SimpleNamespace(value_type=float)
    )
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    monkeypatch.setattr(
        country, "_create_simulation", lambda *_args, **_kwargs: (simulation, system)
    )

    household = requested_household("spm_unit_net_income")
    household["spm_units"]["spm_unit"]["spm_unit_federal_tax"] = {"2024": None}
    result = country.calculate(household, None)

    unit = result.household["spm_units"]["spm_unit"]
    assert unit["spm_unit_net_income"]["2024"] is None
    assert unit["spm_unit_federal_tax"]["2024"] == 1234.0


@pytest.mark.parametrize(
    "code",
    [
        "SPM_CONFIGURATION_UNAVAILABLE",
        "SPM_SETTINGS_INVALID",
        "SPM_SETTINGS_UNSUPPORTED",
    ],
)
@pytest.mark.parametrize("axes", [False, True])
def test_a_configuration_failure_is_never_left_as_a_null_cell(monkeypatch, code, axes):
    """Nulling this would publish "cannot certify" as "computed nothing".

    Leaving a dependant unavailable is only ever right for a missing primitive.
    A build that cannot certify the measurement at all has not computed a null.
    """
    error = spm.SPMValidationError(code, "This build cannot certify the measurement")
    country = _country_raising(monkeypatch, error)
    with pytest.raises(spm.SPMValidationError) as caught:
        country.calculate(requested_household("spm_unit_net_income", axes=axes), None)
    assert caught.value is error


def test_country_passes_resolved_spm_and_uses_the_simulations_private_system(
    monkeypatch,
):
    selection = spm.SPMSelection(geography_kind="national").model_dump()
    monkeypatch.setattr(
        country_module, "normalize_spm_selection", lambda _country, _chosen: selection
    )

    class Simulation:
        def __init__(self, *, tax_benefit_system, situation, spm):
            self.tax_benefit_system = object()
            self.spm_config = spm

    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    country.country_id = "us"
    country.country_package = SimpleNamespace(Simulation=Simulation)
    country.tax_benefit_system = object()
    simulation, system = country._create_simulation({}, None, spm=selection)
    assert simulation.spm_config == selection
    assert system is simulation.tax_benefit_system
    assert system is not country.tax_benefit_system


def test_tax_only_result_reads_provenance_without_calculating_spm(monkeypatch):
    calculations = []
    selection = spm.SPMSelection(
        forecast_content_sha256="a" * 64,
        scenario="baseline",
        geography_kind="national",
        geography_id=None,
        county_vintage="2020",
        as_of=None,
    ).model_dump()
    receipt = country_receipt(selection)

    def calculate(variable, _period):
        calculations.append(variable)
        assert variable == "spm_unit_federal_tax"
        return np.array([123.0])

    simulation = SimpleNamespace(
        calculate=calculate,
        get_population=lambda _entity: SimpleNamespace(get_index=lambda _entity_id: 0),
        spm_config=selection,
        spm_provenance=lambda: receipt,
    )
    system = SimpleNamespace(
        get_variable=lambda _name: SimpleNamespace(value_type=float)
    )
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    monkeypatch.setattr(
        country, "_create_simulation", lambda *_args, **_kwargs: (simulation, system)
    )
    result = country.calculate(requested_household("spm_unit_federal_tax"), None)
    assert calculations == ["spm_unit_federal_tax"]
    assert result.spm_provenance["years"] == []
    assert (
        result.household["spm_units"]["spm_unit"]["spm_unit_federal_tax"]["2024"] == 123
    )
    assert result.spm_provenance == {
        "schema_version": "canonical-spm-provenance-v2",
        "forecast_id": "test-artifact",
        "forecast_sha256": "a" * 64,
        "scenario": "baseline",
        "geography_kind": "national",
        "geography_id": None,
        "county_vintage": "2020",
        "as_of": None,
        "years": [],
        "runtime_versions": receipt["runtime_versions"],
    }


def _country_calculating(monkeypatch, calculate, *, spm_years=()):
    """Return a US country over stand-in simulations, and the selections they get.

    Each simulation calculates with `calculate`, keeps the SPM selection it was
    built with, and reports a receipt for it that measures `spm_years`.
    """
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    country.country_id = "us"
    country.metadata = STAND_IN_METADATA
    selections = []

    def create_simulation(_household, _reform, spm=None):
        selections.append(spm)
        simulation = SimpleNamespace(
            calculate=calculate,
            get_population=lambda _entity: SimpleNamespace(
                get_index=lambda _entity_id: 0, count=AXIS_POINTS
            ),
            spm_config=spm,
            spm_provenance=lambda: country_receipt(spm, spm_years),
        )
        system = SimpleNamespace(
            get_variable=lambda _name: SimpleNamespace(value_type=float),
            variables=HOUSEHOLD_VARIABLES,
        )
        return simulation, system

    monkeypatch.setattr(country, "_create_simulation", create_simulation)
    return country, selections


def _calculate_refusing(refused_variable, error):
    """Calculate every variable but `refused_variable`, which raises `error`."""

    def calculate(variable, _period):
        if variable == refused_variable:
            raise error
        return np.full(AXIS_POINTS, CALCULATED_VALUE)

    return calculate


def _calculate_any_variable(_variable, _period):
    return np.full(AXIS_POINTS, CALCULATED_VALUE)


def _stand_in_geography_factor(_year, _tenure, *, kind, geoid=None, **_settings):
    """Price any geography except a metro area other than the one this forecast has."""
    if kind == "metro" and geoid != STAND_IN_AREA:
        msg = f"No geography factor for area {geoid}"
        raise ValueError(msg)
    return 1.0


@pytest.fixture
def certified_bundle(monkeypatch):
    """Stand in for a certified bundle and its forecast, as the route tests do."""
    bundle = {
        "measurements": {
            "spm": {"forecast_content_sha256": FORECAST_SHA256, "scenario": "baseline"}
        }
    }
    monkeypatch.setattr(spm, "_current_bundle", lambda: bundle)
    monkeypatch.setattr(spm, "simulation_supports_spm", lambda _simulation_type: True)
    monkeypatch.setattr(
        spm,
        "_selected_forecast",
        lambda _expected_sha256: SimpleNamespace(
            years=[2022],
            entry=lambda *_args, **_kwargs: {},
            geography_factor=_stand_in_geography_factor,
        ),
    )


@pytest.fixture
def http_client_for(monkeypatch, certified_bundle, orm_session_factory):
    """Return a factory of Flask clients whose household routes use one country.

    Households are stored in the test database, and calculations are cached in
    memory.
    """

    def client_for(country):
        service = HouseholdCalculationService(
            primary_session_factory=orm_session_factory,
            cache=HouseholdCalculationCache(
                InMemoryCacheBackend(), CacheNamespace("test", "country-spm")
            ),
            country_provider=lambda: {"us": country},
        )
        monkeypatch.setattr(household_routes, "household_calculation_service", service)
        monkeypatch.setattr(
            household_routes, "household_service", HouseholdService(orm_session_factory)
        )
        app = Flask(__name__)
        app.config.update(TESTING=True, CACHE_TYPE="SimpleCache")
        cache.init_app(app)
        app.register_blueprint(household_routes.household_bp)
        return app.test_client()

    return client_for


def _no_county_fips_message(county_fips):
    return (
        f"County selection has no county FIPS input ({county_fips!r}): send "
        'county_fips as a five-digit string (for example "06037"), or select '
        'geography_kind="national" in the spm configuration'
    )


@dataclass(frozen=True)
class MissingInputCase:
    """A household that lacks an SPM input, and the error the installed model raises.

    The code and message are the installed US model's for this household, so
    the tests show what the API does with that error.
    """

    code: str
    message: str
    geography_kind: str = "county"
    county_fips: str | None = None
    age: int = 40
    year: str = "2024"

    def household(self, *, axes=False):
        """Return a household asking for the threshold that lacks this input."""
        household = requested_household(axes=axes, year=self.year)
        household["people"]["you"]["age"] = {self.year: self.age}
        household["spm_units"]["spm_unit"]["spm_unit_federal_tax"] = {self.year: None}
        if self.county_fips is not None:
            household["households"]["household"]["county_fips"] = {
                self.year: self.county_fips
            }
        return household


MISSING_INPUT_CASES = {
    "no-county": MissingInputCase(
        "SPM_GEOGRAPHY_REQUIRED", _no_county_fips_message("")
    ),
    "county-not-a-fips-code": MissingInputCase(
        "SPM_GEOGRAPHY_REQUIRED",
        _no_county_fips_message("malformed"),
        county_fips="malformed",
    ),
    "unplaceable-county": MissingInputCase(
        "SPM_GEOGRAPHY_UNAVAILABLE",
        "County assignment unavailable for 99999/2024",
        county_fips="99999",
    ),
    "no-classified-adult": MissingInputCase(
        "SPM_COMPOSITION_REQUIRED",
        "SPM unit has no classified adult: supply source-backed independence or "
        "household head/spouse structure",
        geography_kind="national",
        age=14,
    ),
    "year-after-forecast": MissingInputCase(
        "SPM_YEAR_UNAVAILABLE",
        "Forecast has no entry for 2036",
        geography_kind="national",
        year="2036",
    ),
}


def test_missing_input_cases_cover_every_spm_input_error_code():
    codes = {case.code for case in MISSING_INPUT_CASES.values()}
    assert codes == spm.SPM_INPUT_ERROR_CODES


@pytest.mark.parametrize(
    "case", MISSING_INPUT_CASES.values(), ids=MISSING_INPUT_CASES.keys()
)
@pytest.mark.parametrize("axes", [False, True])
def test_http_reports_a_chosen_measurements_missing_input_as_a_400(
    monkeypatch, http_client_for, case, axes
):
    """The request sends `spm`, so the caller chose the measurement it asked for."""
    error = _spm_input_error(case.code, case.message)
    country, _ = _country_calculating(
        monkeypatch, _calculate_refusing("spm_unit_spm_threshold", error)
    )
    response = http_client_for(country).post(
        "/us/calculate",
        json={
            "household": case.household(axes=axes),
            "spm": {"geography_kind": case.geography_kind},
        },
    )
    assert response.status_code == 400, response.json
    assert response.json == {
        "status": "error",
        "message": case.message,
        "result": None,
        "errors": [{"code": case.code, "message": case.message}],
    }


@pytest.mark.parametrize(
    "case", MISSING_INPUT_CASES.values(), ids=MISSING_INPUT_CASES.keys()
)
@pytest.mark.parametrize("axes", [False, True])
def test_http_returns_an_inherited_measurements_dependants_as_null(
    monkeypatch, http_client_for, case, axes
):
    """The same household, without `spm`, keeps HTTP 200 and loses only a dependant.

    An axes request spells the null as one per axis point, beside a warning.
    """
    error = _spm_input_error(case.code, case.message)
    country, _ = _country_calculating(
        monkeypatch, _calculate_refusing("spm_unit_spm_threshold", error)
    )
    response = http_client_for(country).post(
        "/us/calculate", json={"household": case.household(axes=axes)}
    )
    assert response.status_code == 200, response.json
    assert response.json["status"] == "ok"
    unit = response.json["result"]["spm_units"]["spm_unit"]
    assert unit["spm_unit_spm_threshold"][case.year] == (
        [None] * AXIS_POINTS if axes else None
    )
    assert unit["spm_unit_federal_tax"][case.year] == (
        [CALCULATED_VALUE] * AXIS_POINTS if axes else CALCULATED_VALUE
    )
    warnings = response.json.get("warnings", [])
    assert any(case.message in warning for warning in warnings) is axes
    assert response.json["spm_provenance"]["geography_kind"] == "county"


def test_http_reports_an_area_the_forecast_lacks_before_any_simulation(
    monkeypatch, http_client_for
):
    """The API checks a chosen area against the forecast before the country runs."""
    message = "SPM area is unavailable in the selected artifact: unknown-area"
    country, selections = _country_calculating(monkeypatch, _calculate_any_variable)
    response = http_client_for(country).post(
        "/us/calculate",
        json={
            "household": requested_household(),
            "spm": {"geography_kind": "metro", "geography_id": "unknown-area"},
        },
    )
    assert response.status_code == 400, response.json
    assert response.json == {
        "status": "error",
        "message": message,
        "result": None,
        "errors": [{"code": "SPM_GEOGRAPHY_UNAVAILABLE", "message": message}],
    }
    assert selections == []


@pytest.mark.parametrize(
    "selection",
    [
        {"geography_kind": "national"},
        {"geography_kind": "county"},
        {"geography_kind": "metro", "geography_id": STAND_IN_AREA},
    ],
    ids=["national", "county", "metro"],
)
def test_http_explicit_geography_returns_the_threshold_and_its_receipt(
    monkeypatch, http_client_for, selection
):
    """The response carries the compact receipt for the geography the caller chose."""
    country, selections = _country_calculating(
        monkeypatch, _calculate_any_variable, spm_years=("2024",)
    )
    household = requested_household()
    household["households"]["household"]["county_fips"] = {"2024": "06037"}
    response = http_client_for(country).post(
        "/us/calculate", json={"household": household, "spm": selection}
    )
    assert response.status_code == 200, response.json
    unit = response.json["result"]["spm_units"]["spm_unit"]
    assert unit["spm_unit_spm_threshold"]["2024"] == CALCULATED_VALUE
    assert response.json["spm_provenance"] == {
        "schema_version": "canonical-spm-provenance-v2",
        "forecast_id": "test-artifact",
        "forecast_sha256": FORECAST_SHA256,
        "scenario": "baseline",
        "geography_kind": selection["geography_kind"],
        "geography_id": selection.get("geography_id"),
        "county_vintage": "2020",
        "as_of": None,
        "years": ["2024"],
        "runtime_versions": STAND_IN_RUNTIME_VERSIONS,
    }
    assert [chosen["geography_kind"] for chosen in selections] == [
        selection["geography_kind"]
    ]


def test_http_tax_only_result_carries_a_receipt_that_measured_no_year(
    monkeypatch, http_client_for
):
    """Only the requested tax is calculated, and its receipt names the chosen area."""
    calculations = []

    def calculate(variable, _period):
        calculations.append(variable)
        return np.full(AXIS_POINTS, CALCULATED_VALUE)

    country, _ = _country_calculating(monkeypatch, calculate)
    response = http_client_for(country).post(
        "/us/calculate",
        json={
            "household": requested_household("spm_unit_federal_tax"),
            "spm": {"geography_kind": "metro", "geography_id": STAND_IN_AREA},
        },
    )
    assert response.status_code == 200, response.json
    assert calculations == ["spm_unit_federal_tax"]
    unit = response.json["result"]["spm_units"]["spm_unit"]
    assert unit["spm_unit_federal_tax"]["2024"] == CALCULATED_VALUE
    receipt = response.json["spm_provenance"]
    assert receipt["geography_kind"] == "metro"
    assert receipt["geography_id"] == STAND_IN_AREA
    assert receipt["years"] == []


def test_http_full_calculation_adds_omitted_variables_under_the_chosen_measurement(
    monkeypatch, http_client_for
):
    """`/calculate-full` asks the country for every yearly variable left out."""
    calculations = []

    def calculate(variable, period):
        calculations.append((variable, period))
        return np.full(AXIS_POINTS, CALCULATED_VALUE)

    country, selections = _country_calculating(
        monkeypatch, calculate, spm_years=("2024",)
    )
    household = {
        "people": {"you": {"age": {"2024": 40}}},
        "households": {"household": {"members": ["you"]}},
        "spm_units": {"spm_unit": {"members": ["you"]}},
    }
    response = http_client_for(country).post(
        "/us/calculate-full",
        json={"household": household, "spm": {"geography_kind": "national"}},
    )
    assert response.status_code == 200, response.json
    assert sorted(calculations) == [
        ("spm_unit_federal_tax", "2024"),
        ("spm_unit_net_income", "2024"),
        ("spm_unit_spm_threshold", "2024"),
    ]
    result = response.json["result"]
    assert result["people"]["you"]["employment_income"] == {"2024": 0}
    assert result["households"]["household"]["state_code"] == {"2024": "CA"}
    assert result["spm_units"]["spm_unit"]["spm_unit_spm_threshold"] == {
        "2024": CALCULATED_VALUE
    }
    assert [chosen["geography_kind"] for chosen in selections] == ["national"]
    assert response.json["spm_provenance"]["geography_kind"] == "national"
    assert response.json["spm_provenance"]["years"] == ["2024"]


def test_http_stored_household_replays_its_saved_selection_once_then_from_the_cache(
    monkeypatch, http_client_for, orm_session_factory
):
    """A replay calculates the saved selection, and a second replay reads the cache."""
    with orm_session_factory.begin() as session:
        session.add(
            Policy(
                id=CURRENT_LAW_POLICY_ID,
                country_id="us",
                policy_json={},
                policy_hash="baseline",
                api_version="test",
            )
        )
    country, selections = _country_calculating(
        monkeypatch, _calculate_any_variable, spm_years=("2024",)
    )
    client = http_client_for(country)
    created = client.post(
        "/us/household",
        json={"data": requested_household(), "spm": {"geography_kind": "national"}},
    )
    assert created.status_code == 201, created.json
    household_id = created.json["result"]["household_id"]
    stored = client.get(f"/us/household/{household_id}").json["result"]["spm"]
    assert stored["geography_kind"] == "national"
    assert stored["forecast_content_sha256"] == FORECAST_SHA256

    url = f"/us/household/{household_id}/policy/{CURRENT_LAW_POLICY_ID}"
    response = client.get(url)
    cached = client.get(url)

    assert response.status_code == 200, response.json
    assert cached.json == response.json
    assert selections == [stored]
    unit = response.json["result"]["spm_units"]["spm_unit"]
    assert unit["spm_unit_spm_threshold"]["2024"] == CALCULATED_VALUE
    assert response.json["spm_provenance"]["geography_kind"] == "national"
    assert response.json["spm_provenance"]["years"] == ["2024"]


def test_uncertifiable_country_receipt_does_not_become_an_internal_failure(monkeypatch):
    """A receipt shape this API cannot read is a typed 400, not a 500.

    The calculation itself succeeded, so the per-variable fallback never runs;
    the receipt is read once at the end and must carry a public SPM code.
    """
    selection = spm.SPMSelection(geography_kind="national").model_dump()
    simulation = SimpleNamespace(
        calculate=lambda _variable, _period: np.array([123.0]),
        get_population=lambda _entity: SimpleNamespace(get_index=lambda _entity_id: 0),
        spm_config={**selection, "threshold_method": "unreviewed"},
        spm_provenance=dict,
    )
    system = SimpleNamespace(
        get_variable=lambda _name: SimpleNamespace(value_type=float)
    )
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    monkeypatch.setattr(
        country, "_create_simulation", lambda *_args, **_kwargs: (simulation, system)
    )
    with pytest.raises(spm.SPMValidationError) as caught:
        country.calculate(requested_household("spm_unit_federal_tax"), None)
    assert caught.value.code == "SPM_CONFIGURATION_UNAVAILABLE"
    assert spm.spm_error_detail(caught.value) == caught.value.to_dict()
