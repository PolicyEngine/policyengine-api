"""The household years in each country's metadata (``household_options``)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from policyengine_us.data.economic_assumptions import CPI_U_PARAM_PATH
from spm_calculator.rolling_forecast import load_forecast

from policyengine_api import country as country_module
from policyengine_api.country import COUNTRIES, PolicyEngineCountry
from policyengine_api.economy_years import uk_economy_years
from policyengine_api.household_years import us_household_years
from policyengine_api.services.metadata_service import MetadataService
from policyengine_api.spm import normalize_spm_selection

# The US society-wide years as master lists them, newest first. This pull
# request leaves them unchanged.
US_SOCIETY_WIDE_YEARS = list(range(2035, 2021, -1))


def _metadata(country_id):
    return MetadataService().get_metadata(country_id)


def _year_names(time_period):
    return [period["name"] for period in time_period]


class _ParameterTreeStandIn:
    """Stands in for a parameter tree holding only the CPI-U parameter."""

    def __init__(self, cpi_u_file):
        self.cpi_u_file = cpi_u_file

    def get_child(self, path):
        assert path == CPI_U_PARAM_PATH
        return SimpleNamespace(file_path=str(self.cpi_u_file))


def _country_stand_in(country_id):
    country = PolicyEngineCountry.__new__(PolicyEngineCountry)
    country.country_id = country_id
    country.tax_benefit_system = SimpleNamespace(parameters=object())
    return country


def test_us_household_years_stop_at_the_last_cpi_u_year_newest_first(tmp_path):
    cpi_u_file = tmp_path / "cpi_u.yaml"
    cpi_u_file.write_text(
        yaml.safe_dump({"values": {"2013-01-01": 233.0, "2033-01-01": 340.0}})
    )

    years = us_household_years(
        _ParameterTreeStandIn(cpi_u_file), [2023, 2022, 2033, 2034, 2035, 2023]
    )

    assert years == [2033, 2023, 2022]


def test_us_household_years_are_the_society_wide_years_without_a_forecast(
    monkeypatch,
):
    monkeypatch.setattr(country_module, "certified_spm_forecast_years", lambda: None)
    economy_time_period = [
        {"name": year, "label": str(year)} for year in US_SOCIETY_WIDE_YEARS
    ]

    options = _country_stand_in("us").build_household_options(
        {"time_period": economy_time_period}
    )

    assert options == {"time_period": economy_time_period}


def test_a_country_without_household_rules_offers_its_society_wide_years():
    economy_time_period = [{"name": 2026, "label": "2026"}]

    options = _country_stand_in("ca").build_household_options(
        {"time_period": economy_time_period}
    )

    assert options == {"time_period": economy_time_period}


def test_us_household_years_are_the_certified_forecast_years_to_cpi_u():
    """The US years come from the installed bundle's forecast and CPI-U file."""
    forecast_sha256 = normalize_spm_selection("us", None)["forecast_content_sha256"]
    forecast_years = load_forecast(expected_sha256=forecast_sha256).years
    cpi_u_file = Path(
        COUNTRIES["us"]
        .tax_benefit_system.parameters.get_child(CPI_U_PARAM_PATH)
        .file_path
    )
    cpi_u_values = yaml.safe_load(cpi_u_file.read_text())["values"]
    last_cpi_u_year = max(int(str(instant)[:4]) for instant in cpi_u_values)

    time_period = _metadata("us")["household_options"]["time_period"]

    assert _year_names(time_period) == sorted(
        (year for year in forecast_years if year <= last_cpi_u_year), reverse=True
    )


def test_us_household_years_include_2022_and_2023():
    """Household calculations stay available for 2022 and 2023."""
    time_period = _metadata("us")["household_options"]["time_period"]

    assert {2022, 2023} <= set(_year_names(time_period))


def test_uk_household_years_follow_the_uk_society_wide_rule():
    parameters = COUNTRIES["uk"].tax_benefit_system.parameters

    time_period = _metadata("uk")["household_options"]["time_period"]

    assert _year_names(time_period) == uk_economy_years(parameters)


@pytest.mark.parametrize("country_id", COUNTRIES)
def test_household_years_have_the_shape_of_society_wide_years(country_id):
    metadata = _metadata(country_id)
    household_time_period = metadata["household_options"]["time_period"]
    economy_keys = {
        frozenset(period) for period in metadata["economy_options"]["time_period"]
    }

    assert household_time_period
    for period in household_time_period:
        assert {frozenset(period)} == economy_keys == {frozenset({"name", "label"})}
        assert type(period["name"]) is int
        assert period["label"] == str(period["name"])


def test_us_society_wide_years_are_unchanged():
    assert _metadata("us")["economy_options"]["time_period"] == [
        {"name": year, "label": str(year)} for year in US_SOCIETY_WIDE_YEARS
    ]


def test_uk_society_wide_years_are_unchanged():
    parameters = COUNTRIES["uk"].tax_benefit_system.parameters

    assert _metadata("uk")["economy_options"]["time_period"] == [
        {"name": year, "label": str(year)} for year in uk_economy_years(parameters)
    ]
