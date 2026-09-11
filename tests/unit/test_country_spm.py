"""Exercise the API country adapter, including optional real canonical runtime."""

from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from policyengine_api import country as country_module
from policyengine_api import spm
from policyengine_api.country import COUNTRIES, PolicyEngineCountry


# An axes request expands every recognized variable, so a stub system must name
# the ones these households carry; anything else (entity membership) is skipped.
HOUSEHOLD_VARIABLES = {
    "age",
    "employment_income",
    "state_code",
    "spm_unit_federal_tax",
    "spm_unit_net_income",
    "spm_unit_spm_threshold",
}
AXIS_POINTS = 2


def requested_household(variable="spm_unit_spm_threshold", *, axes=False):
    household = {
        "people": {"you": {"age": {"2024": 40}}},
        "households": {"household": {"members": ["you"], "state_code": {"2024": "CA"}}},
        "spm_units": {"spm_unit": {"members": ["you"], variable: {"2024": None}}},
    }
    if axes:
        household["axes"] = [
            [
                {
                    "name": "employment_income",
                    "period": "2024",
                    "count": AXIS_POINTS,
                    "min": 0,
                    "max": 100,
                }
            ]
        ]
    return household


def _country_raising(monkeypatch, error):
    """A country whose every variable calculation raises `error`."""

    def calculate(variable, period):
        # This also represents a requested resource with a nested SPM dependency.
        raise error

    simulation = SimpleNamespace(
        calculate=calculate,
        get_population=lambda entity: SimpleNamespace(
            get_index=lambda entity_id: 0, count=AXIS_POINTS
        ),
    )
    system = SimpleNamespace(
        get_variable=lambda name: object(), variables=HOUSEHOLD_VARIABLES
    )
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    monkeypatch.setattr(
        country, "_create_simulation", lambda *args, **kwargs: (simulation, system)
    )
    return country


def _failing_country(monkeypatch, code):
    error = ValueError("Missing or unavailable explicit SPM input")
    error.code = code
    return _country_raising(monkeypatch, error), error


@pytest.mark.parametrize("code", sorted(spm.SPM_INPUT_ERROR_CODES))
@pytest.mark.parametrize("axes", [False, True])
def test_country_never_swallows_spm_input_errors_for_a_chosen_measurement(
    monkeypatch, code, axes
):
    country, error = _failing_country(monkeypatch, code)
    with pytest.raises(ValueError) as caught:
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
    """Nobody chose this measurement, so its dependants behave like any other
    variable the model cannot compute: null, not a rejected request."""
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

    def calculate(variable, period):
        if variable == "spm_unit_net_income":
            raise error
        return np.array([1234.0])

    simulation = SimpleNamespace(
        calculate=calculate,
        get_population=lambda entity: SimpleNamespace(get_index=lambda entity_id: 0),
    )
    system = SimpleNamespace(
        get_variable=lambda name: SimpleNamespace(value_type=float)
    )
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    monkeypatch.setattr(
        country, "_create_simulation", lambda *args, **kwargs: (simulation, system)
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
        country_module, "normalize_spm_selection", lambda country, chosen: selection
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
    selection = spm.SPMSelection(geography_kind="national").model_dump()
    receipt = {
        "forecast_id": "test-artifact",
        "forecast_sha256": "a" * 64,
        "scenario": "baseline",
        "geography_kind": "national",
        "runtime_versions": {"policyengine-us": "test"},
        "years": {},
        "geographies": [],
        "composition_method": "test adult classification",
        "storage_method": "test final cast",
    }

    def calculate(variable, period):
        calculations.append(variable)
        assert variable == "spm_unit_federal_tax"
        return np.array([123.0])

    simulation = SimpleNamespace(
        calculate=calculate,
        get_population=lambda entity: SimpleNamespace(get_index=lambda entity_id: 0),
        spm_config=selection,
        spm_provenance=lambda: receipt,
    )
    system = SimpleNamespace(
        get_variable=lambda name: SimpleNamespace(value_type=float)
    )
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    monkeypatch.setattr(
        country, "_create_simulation", lambda *args, **kwargs: (simulation, system)
    )
    result = country.calculate(requested_household("spm_unit_federal_tax"), None)
    assert calculations == ["spm_unit_federal_tax"]
    assert result.spm_provenance["years"] == {}
    assert (
        result.household["spm_units"]["spm_unit"]["spm_unit_federal_tax"]["2024"] == 123
    )
    assert json.loads(json.dumps(result.spm_config)) == selection
    assert json.loads(json.dumps(result.spm_provenance)) == receipt


@pytest.fixture
def real_canonical_country(monkeypatch):
    """Test-only certification projection, never a release/published bundle claim."""
    country = COUNTRIES["us"]
    if not spm.simulation_supports_spm(country.country_package.Simulation):
        pytest.skip("Requires the coordinated canonical US model and calculator source")
    from spm_calculator.rolling_forecast import load_forecast

    forecast = load_forecast()
    bundle = {
        "measurements": {
            "spm": {
                "forecast_content_sha256": forecast.content_sha256,
                "scenario": forecast.default_scenario,
            }
        }
    }
    monkeypatch.setattr(spm, "_current_bundle", lambda: bundle)
    return country


def test_real_country_state_only_tax_succeeds_and_receipt_stays_empty(
    real_canonical_country,
):
    result = real_canonical_country.calculate(
        requested_household("spm_unit_federal_tax"), None
    )
    assert (
        result.household["spm_units"]["spm_unit"]["spm_unit_federal_tax"]["2024"]
        is not None
    )
    assert result.spm_provenance["years"] == {}
    json.dumps(result.spm_provenance)


@pytest.mark.parametrize(
    "variable",
    [
        "spm_unit_spm_threshold",
        "spm_unit_capped_housing_subsidy",
        "spm_unit_net_income",
        "spm_unit_is_in_spm_poverty",
    ],
)
def test_real_country_state_only_spm_dependency_requires_geography(
    real_canonical_country, variable
):
    """A household that chose this measurement is told what it is missing."""
    with pytest.raises(ValueError) as caught:
        real_canonical_country.calculate(
            requested_household(variable), None, spm_requested=True
        )
    assert spm.spm_error_detail(caught.value)["code"] == "SPM_GEOGRAPHY_REQUIRED"


@pytest.mark.parametrize(
    "variable",
    [
        "spm_unit_spm_threshold",
        "spm_unit_capped_housing_subsidy",
        "spm_unit_net_income",
        "spm_unit_is_in_spm_poverty",
    ],
)
def test_real_country_state_only_dependency_is_null_when_nothing_was_chosen(
    real_canonical_country, variable
):
    """The commitment in docs/canonical-spm.md, against the real model.

    Certifying a bundle must not make a state-only household uncalculable. The
    inherited default was not a choice, so the dependant is unavailable rather
    than the request rejected.
    """
    result = real_canonical_country.calculate(requested_household(variable), None)
    assert result.household["spm_units"]["spm_unit"][variable]["2024"] is None
    assert result.spm_config["geography_kind"] == "county"


@pytest.mark.parametrize("county", ["99999", "malformed"])
def test_real_country_unknown_county_is_structured(real_canonical_country, county):
    household = requested_household()
    household["households"]["household"]["county_fips"] = {"2024": county}
    with pytest.raises(ValueError) as caught:
        real_canonical_country.calculate(household, None, spm_requested=True)
    assert spm.spm_error_detail(caught.value)["code"] == "SPM_GEOGRAPHY_UNAVAILABLE"


def test_real_country_unknown_area_is_structured(real_canonical_country):
    with pytest.raises(ValueError) as caught:
        real_canonical_country.calculate(
            requested_household(),
            None,
            spm={"geography_kind": "metro", "geography_id": "unknown-area"},
            spm_requested=True,
        )
    assert spm.spm_error_detail(caught.value)["code"] == "SPM_GEOGRAPHY_UNAVAILABLE"


def test_real_country_unclassified_composition_is_structured(real_canonical_country):
    household = requested_household()
    household["people"]["you"]["age"] = {"2024": 14}
    with pytest.raises(ValueError) as caught:
        real_canonical_country.calculate(
            household, None, spm={"geography_kind": "national"}, spm_requested=True
        )
    assert spm.spm_error_detail(caught.value)["code"] == "SPM_COMPOSITION_REQUIRED"


@pytest.mark.parametrize("geography", ["national", "county", "metro"])
def test_real_country_explicit_geography_yields_json_receipt(
    real_canonical_country, geography
):
    household = requested_household()
    selection = {"geography_kind": geography}
    if geography == "county":
        household["households"]["household"]["county_fips"] = {"2024": "06037"}
    elif geography == "metro":
        resolved = spm.normalize_spm_selection("us", None)
        forecast = spm._selected_forecast(resolved["forecast_content_sha256"])
        selection["geography_id"] = forecast.resolve_county(2024, "06037")["area_id"]
    original = deepcopy(household)
    result = real_canonical_country.calculate(
        household, None, spm=selection, spm_requested=True
    )
    assert household == original
    assert (
        result.household["spm_units"]["spm_unit"]["spm_unit_spm_threshold"]["2024"] > 0
    )
    assert result.spm_config["geography_kind"] == geography
    assert (
        result.spm_provenance["forecast_sha256"]
        == result.spm_config["forecast_content_sha256"]
    )
    assert "2024" in result.spm_provenance["years"]
    json.dumps(result.spm_provenance)


@pytest.fixture
def real_http_client(real_canonical_country, monkeypatch, orm_session_factory):
    from flask import Flask

    from policyengine_api.extensions import cache
    from policyengine_api.data.v1_models import Policy
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

    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=HouseholdCalculationCache(
            InMemoryCacheBackend(), CacheNamespace("test", "real-spm")
        ),
        country_provider=lambda: {"us": real_canonical_country},
    )
    monkeypatch.setattr(household_routes, "household_calculation_service", service)
    monkeypatch.setattr(
        household_routes, "household_service", HouseholdService(orm_session_factory)
    )
    with orm_session_factory.begin() as session:
        session.add(
            Policy(
                id=2,
                country_id="us",
                policy_json={},
                policy_hash="baseline",
                api_version="test",
            )
        )
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="SimpleCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    with app.app_context():
        cache.clear()
    return app.test_client()


def test_real_http_tax_only_succeeds_without_geography(real_http_client):
    response = real_http_client.post(
        "/us/calculate",
        json={"household": requested_household("spm_unit_federal_tax")},
    )
    assert response.status_code == 200, response.json
    assert response.json["spm_provenance"]["years"] == {}


@pytest.mark.parametrize(
    "kind,code",
    [
        ("state-only", "SPM_GEOGRAPHY_REQUIRED"),
        ("axes", "SPM_GEOGRAPHY_REQUIRED"),
        ("county", "SPM_GEOGRAPHY_UNAVAILABLE"),
        ("metro", "SPM_GEOGRAPHY_UNAVAILABLE"),
        ("composition", "SPM_COMPOSITION_REQUIRED"),
    ],
)
def test_real_http_spm_errors_use_validation_response(real_http_client, kind, code):
    """Every case here sends `spm`: the caller chose the measurement it asked for."""
    household = requested_household(axes=kind == "axes")
    payload = {"household": household, "spm": {"geography_kind": "county"}}
    if kind == "county":
        household["households"]["household"]["county_fips"] = {"2024": "99999"}
    elif kind == "metro":
        payload["spm"] = {"geography_kind": "metro", "geography_id": "unknown-area"}
    elif kind == "composition":
        household["people"]["you"]["age"] = {"2024": 14}
        payload["spm"] = {"geography_kind": "national"}
    response = real_http_client.post("/us/calculate", json=payload)
    assert response.status_code == 400, response.json
    assert response.json["status"] == "error"
    assert response.json["result"] is None
    assert response.json["errors"][0]["code"] == code
    assert response.json["message"] == response.json["errors"][0]["message"]


@pytest.mark.parametrize("kind", ["state-only", "axes", "county", "composition"])
def test_real_http_missing_primitives_are_null_when_nothing_was_chosen(
    real_http_client, kind
):
    """The same households, with no `spm`, are calculated rather than rejected.

    This is the caller-visible half of the commitment: a request that never
    chose a measurement keeps its HTTP 200 and loses only the cells that needed
    the missing primitive.
    """
    household = requested_household(axes=kind == "axes")
    if kind == "county":
        household["households"]["household"]["county_fips"] = {"2024": "99999"}
    elif kind == "composition":
        household["people"]["you"]["age"] = {"2024": 14}
    response = real_http_client.post("/us/calculate", json={"household": household})
    assert response.status_code == 200, response.json
    assert response.json["status"] == "ok"
    assert response.json["spm_config"]["geography_kind"] == "county"
    if kind != "axes":
        threshold = response.json["result"]["spm_units"]["spm_unit"][
            "spm_unit_spm_threshold"
        ]["2024"]
        assert threshold is None


def test_real_http_national_result_and_receipt_survive_response_cache(real_http_client):
    payload = {
        "household": requested_household(),
        "spm": {"geography_kind": "national"},
    }
    response = real_http_client.post("/us/calculate", json=payload)
    cached = real_http_client.post("/us/calculate", json=payload)
    assert response.status_code == 200, response.json
    assert cached.status_code == 200
    assert cached.json == response.json
    assert response.json["spm_config"]["geography_kind"] == "national"
    assert "2024" in response.json["spm_provenance"]["years"]


def test_real_http_full_national_calculation_keeps_threshold_and_provenance(
    real_http_client,
):
    response = real_http_client.post(
        "/us/calculate-full",
        json={
            "household": requested_household(),
            "spm": {"geography_kind": "national"},
        },
    )
    assert response.status_code == 200, response.json
    assert (
        response.json["result"]["spm_units"]["spm_unit"]["spm_unit_spm_threshold"][
            "2024"
        ]
        > 0
    )
    assert response.json["spm_config"]["geography_kind"] == "national"
    assert "2024" in response.json["spm_provenance"]["years"]


def test_real_http_stored_national_replay_preserves_threshold_and_cached_receipt(
    real_http_client, real_canonical_country, monkeypatch
):
    calls = []
    calculate = real_canonical_country.calculate

    def observed_calculate(*args, **kwargs):
        calls.append(kwargs.get("spm"))
        return calculate(*args, **kwargs)

    monkeypatch.setattr(real_canonical_country, "calculate", observed_calculate)
    created = real_http_client.post(
        "/us/household",
        json={
            "data": requested_household(),
            "spm": {"geography_kind": "national"},
        },
    )
    assert created.status_code == 201, created.json
    household_id = created.json["result"]["household_id"]
    stored = real_http_client.get(f"/us/household/{household_id}")
    assert stored.json["result"]["spm"]["geography_kind"] == "national"
    url = f"/us/household/{household_id}/policy/2"
    response = real_http_client.get(url)
    cached = real_http_client.get(url)
    assert response.status_code == 200, response.json
    assert cached.status_code == 200
    assert cached.json == response.json
    assert len(calls) == 1
    assert calls[0]["geography_kind"] == "national"
    assert (
        response.json["result"]["spm_units"]["spm_unit"]["spm_unit_spm_threshold"][
            "2024"
        ]
        > 0
    )
    assert "2024" in response.json["spm_provenance"]["years"]


def household_in_year(variable, year, *, axes=False):
    """Move every input and requested output to the regression's annual period."""
    return json.loads(
        json.dumps(requested_household(variable, axes=axes)).replace(
            '"2024"', f'"{year}"'
        )
    )


def selection_for_geography(geography):
    selection = {"geography_kind": geography}
    if geography == "metro":
        resolved = spm.normalize_spm_selection("us", None)
        forecast = spm._selected_forecast(resolved["forecast_content_sha256"])
        selection["geography_id"] = forecast.resolve_county(2024, "06037")["area_id"]
    return selection


@pytest.mark.parametrize("geography", ["national", "metro"])
@pytest.mark.parametrize("year", [2021, 2036])
def test_real_http_tax_only_outside_artifact_years_is_lazy(
    real_http_client, geography, year
):
    response = real_http_client.post(
        "/us/calculate",
        json={
            "household": household_in_year("spm_unit_federal_tax", year),
            "spm": selection_for_geography(geography),
        },
    )
    assert response.status_code == 200, response.json
    assert response.json["status"] == "ok"
    assert (
        response.json["result"]["spm_units"]["spm_unit"]["spm_unit_federal_tax"][
            str(year)
        ]
        is not None
    )
    assert response.json["spm_provenance"]["years"] == {}


@pytest.mark.parametrize("geography", ["national", "metro"])
@pytest.mark.parametrize("variable", ["spm_unit_spm_threshold", "spm_unit_net_income"])
@pytest.mark.parametrize("axes", [False, True])
def test_real_http_unsupported_spm_year_is_structured_only_when_calculated(
    real_http_client, geography, variable, axes
):
    response = real_http_client.post(
        "/us/calculate",
        json={
            "household": household_in_year(variable, 2036, axes=axes),
            "spm": selection_for_geography(geography),
        },
    )
    assert response.status_code == 400, response.json
    assert response.json["status"] == "error"
    assert response.json["result"] is None
    assert response.json["errors"][0]["code"] == "SPM_YEAR_UNAVAILABLE"
    assert "2036" in response.json["errors"][0]["message"]


def test_uncertifiable_country_receipt_does_not_become_an_internal_failure(monkeypatch):
    """A receipt shape this API cannot read is a typed 400, not a 500.

    The calculation itself succeeded, so the per-variable fallback never runs;
    the receipt is read once at the end and must carry a public SPM code.
    """
    selection = spm.SPMSelection(geography_kind="national").model_dump()
    simulation = SimpleNamespace(
        calculate=lambda variable, period: np.array([123.0]),
        get_population=lambda entity: SimpleNamespace(get_index=lambda entity_id: 0),
        spm_config={**selection, "threshold_method": "unreviewed"},
        spm_provenance=lambda: {},
    )
    system = SimpleNamespace(
        get_variable=lambda name: SimpleNamespace(value_type=float)
    )
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    monkeypatch.setattr(
        country, "_create_simulation", lambda *args, **kwargs: (simulation, system)
    )
    with pytest.raises(spm.SPMValidationError) as caught:
        country.calculate(requested_household("spm_unit_federal_tax"), None)
    assert caught.value.code == "SPM_CONFIGURATION_UNAVAILABLE"
    assert spm.spm_error_detail(caught.value) == caught.value.to_dict()
