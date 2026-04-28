import copy
import importlib
import sys
import types
from types import SimpleNamespace

import pytest


FAKE_METADATA = {
    "variables": {
        "age": {
            "name": "age",
            "definitionPeriod": "year",
            "entity": "person",
            "isInputVariable": True,
            "defaultValue": 0,
        },
        "employment_income": {
            "name": "employment_income",
            "definitionPeriod": "year",
            "entity": "person",
            "isInputVariable": True,
            "defaultValue": 0,
        },
        "is_tax_unit_dependent": {
            "name": "is_tax_unit_dependent",
            "definitionPeriod": "year",
            "entity": "person",
            "isInputVariable": True,
            "defaultValue": False,
        },
        "tax_due": {
            "name": "tax_due",
            "definitionPeriod": "year",
            "entity": "tax_unit",
            "isInputVariable": False,
            "defaultValue": 0,
        },
        "monthly_rent": {
            "name": "monthly_rent",
            "definitionPeriod": "month",
            "entity": "household",
            "isInputVariable": True,
            "defaultValue": 0,
        },
    },
    "entities": {
        "person": {"plural": "people"},
        "tax_unit": {"plural": "tax_units"},
        "household": {"plural": "households"},
    },
}


BASE_HOUSEHOLD = {
    "people": {
        "you": {
            "age": {"2025": 40},
            "employment_income": {"2025": 30000},
        },
        "partner": {
            "age": {"2025": 40},
        },
    },
    "tax_units": {
        "tax_unit": {
            "members": ["you", "partner"],
        }
    },
}


@pytest.fixture
def household_module(monkeypatch, test_db):
    fake_country = SimpleNamespace(metadata=copy.deepcopy(FAKE_METADATA))
    fake_country_module = types.ModuleType("policyengine_api.country")
    fake_country_module.COUNTRIES = SimpleNamespace(
        get=lambda country_id: fake_country
    )

    monkeypatch.setitem(sys.modules, "policyengine_api.country", fake_country_module)
    sys.modules.pop("policyengine_api.endpoints.household", None)

    module = importlib.import_module("policyengine_api.endpoints.household")
    monkeypatch.setattr(module, "database", test_db)
    monkeypatch.setattr(module, "local_database", test_db)

    return module


def test_get_household_year_uses_age_period_when_present(household_module):
    household = copy.deepcopy(BASE_HOUSEHOLD)

    assert household_module.get_household_year(household) == "2025"


def test_get_household_year_falls_back_to_current_year(monkeypatch, household_module):
    class _FakeDate:
        @staticmethod
        def today():
            return SimpleNamespace(year=2042)

    monkeypatch.setattr(household_module, "date", _FakeDate)

    household = {"people": {"you": {}}, "tax_units": {"tax_unit": {"members": []}}}

    assert household_module.get_household_year(household) == 2042


def test_add_yearly_variables_adds_missing_input_defaults(household_module):
    household = copy.deepcopy(BASE_HOUSEHOLD)

    result = household_module.add_yearly_variables(household, "us")

    assert result["people"]["partner"]["employment_income"] == {"2025": 0}
    assert result["people"]["you"]["is_tax_unit_dependent"] == {"2025": False}


def test_add_yearly_variables_adds_missing_output_as_none(household_module):
    household = copy.deepcopy(BASE_HOUSEHOLD)

    result = household_module.add_yearly_variables(household, "us")

    assert result["tax_units"]["tax_unit"]["tax_due"] == {"2025": None}


def test_add_yearly_variables_adds_monthly_variables_too(household_module):
    household = copy.deepcopy(BASE_HOUSEHOLD)
    household["households"] = {"home": {"members": ["you", "partner"]}}

    result = household_module.add_yearly_variables(household, "us")

    assert result["households"]["home"]["monthly_rent"] == {"2025": 0}


def test_add_yearly_variables_does_not_overwrite_existing_values(household_module):
    household = copy.deepcopy(BASE_HOUSEHOLD)
    household["people"]["partner"]["employment_income"] = {"2025": 12345}
    household["tax_units"]["tax_unit"]["tax_due"] = {"2025": 999}

    result = household_module.add_yearly_variables(household, "us")

    assert result["people"]["partner"]["employment_income"] == {"2025": 12345}
    assert result["tax_units"]["tax_unit"]["tax_due"] == {"2025": 999}
