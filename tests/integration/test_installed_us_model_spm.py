"""Check canonical SPM household calculations against the installed US model.

tests/unit/test_country_spm.py checks every case with stand-in simulations that
raise the installed model's errors and report its receipts. These two tests run
the policyengine-us and spm-calculator versions the bundle installs, to show
that the model, its forecast and the API still agree on those errors and
receipts. Which code the model raises for each missing input is
policyengine-us's to test.

A real calculation takes seconds, so the Flask app and its calculation service
are built once for the session.
"""

from importlib.metadata import version
from typing import NamedTuple

import pytest
from flask import Flask
from flask.testing import FlaskClient

from policyengine_api import spm
from policyengine_api.country import COUNTRIES, PolicyEngineCountry
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

YEAR = "2024"
LOS_ANGELES_COUNTY = "06037"


class InstalledModelHarness(NamedTuple):
    """One Flask client and the calculation service its household routes use."""

    client: FlaskClient
    calculation_service: HouseholdCalculationService


@pytest.fixture(scope="session")
def installed_us_country() -> PolicyEngineCountry:
    """Return the installed US model, certified by the installed bundle's manifest."""
    country = COUNTRIES["us"]
    if not spm.simulation_supports_spm(country.country_package.Simulation):
        pytest.skip("Requires the coordinated canonical US model and calculator source")
    return country


@pytest.fixture(scope="session")
def installed_model_harness(installed_us_country) -> InstalledModelHarness:
    """Build the household routes once, with an in-memory calculation cache."""
    calculation_service = HouseholdCalculationService(
        cache=HouseholdCalculationCache(
            InMemoryCacheBackend(), CacheNamespace("test", "installed-us-model")
        ),
        country_provider=lambda: {"us": installed_us_country},
    )
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="SimpleCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    return InstalledModelHarness(app.test_client(), calculation_service)


@pytest.fixture
def client(monkeypatch, installed_model_harness) -> FlaskClient:
    """Point the household routes at the session's calculation service for one test."""
    monkeypatch.setattr(
        household_routes,
        "household_calculation_service",
        installed_model_harness.calculation_service,
    )
    return installed_model_harness.client


def household_requesting_threshold(*, county_fips=None):
    """Return a one-adult California household asking for its SPM threshold."""
    household = {
        "people": {"you": {"age": {YEAR: 40}}},
        "households": {"household": {"members": ["you"], "state_code": {YEAR: "CA"}}},
        "spm_units": {
            "spm_unit": {"members": ["you"], "spm_unit_spm_threshold": {YEAR: None}}
        },
    }
    if county_fips is not None:
        household["households"]["household"]["county_fips"] = {YEAR: county_fips}
    return household


def spm_threshold(response):
    return response.json["result"]["spm_units"]["spm_unit"]["spm_unit_spm_threshold"][
        YEAR
    ]


def test_a_chosen_county_yields_a_threshold_and_the_installed_forecasts_receipt(
    client,
):
    """The installed model prices a county, and its receipt passes the API's checks.

    The receipt names the forecast the bundle pins and the packages installed.
    """
    response = client.post(
        "/us/calculate",
        json={
            "household": household_requesting_threshold(county_fips=LOS_ANGELES_COUNTY),
            "spm": {"geography_kind": "county"},
        },
    )

    assert response.status_code == 200, response.json
    assert spm_threshold(response) > 0
    receipt = response.json["spm_provenance"]
    defaults = spm.normalize_spm_selection("us", None)
    assert receipt["schema_version"] == "canonical-spm-provenance-v2"
    assert receipt["forecast_sha256"] == defaults["forecast_content_sha256"]
    assert receipt["scenario"] == defaults["scenario"]
    assert receipt["geography_kind"] == "county"
    assert receipt["years"] == [YEAR]
    assert receipt["runtime_versions"]["policyengine-us"] == version("policyengine-us")
    assert receipt["runtime_versions"]["spm-calculator"] == version("spm-calculator")


def test_a_state_only_household_is_rejected_only_when_it_chose_the_measurement(
    client,
):
    """The commitment in docs/canonical-spm.md, against the installed model.

    Without `spm` the household inherits the county default, so the threshold
    it cannot price is null and the rest of the response stands. Sending the
    same county choice makes the model's missing-county error a 400 with its
    own code and text.
    """
    household = household_requesting_threshold()

    inherited = client.post("/us/calculate", json={"household": household})
    chosen = client.post(
        "/us/calculate",
        json={"household": household, "spm": {"geography_kind": "county"}},
    )

    assert inherited.status_code == 200, inherited.json
    assert spm_threshold(inherited) is None
    assert inherited.json["spm_provenance"]["geography_kind"] == "county"
    assert chosen.status_code == 400, chosen.json
    error = chosen.json["errors"][0]
    assert error["code"] == "SPM_GEOGRAPHY_REQUIRED"
    assert "County selection has no county FIPS input" in error["message"]
