import copy
from types import SimpleNamespace

from policyengine_api.endpoints.household import add_yearly_variables


TEST_YEAR = "2023"


def fake_country_metadata():
    return {
        "entities": {
            "person": {"plural": "people"},
            "household": {"plural": "households"},
        },
        "variables": {
            "age": {
                "definitionPeriod": "year",
                "entity": "person",
                "name": "age",
                "isInputVariable": True,
                "defaultValue": 0,
            },
            "employment_income": {
                "definitionPeriod": "year",
                "entity": "person",
                "name": "employment_income",
                "isInputVariable": True,
                "defaultValue": 0,
            },
            "household_net_income": {
                "definitionPeriod": "year",
                "entity": "household",
                "name": "household_net_income",
                "isInputVariable": False,
                "defaultValue": None,
            },
            "monthly_benefit": {
                "definitionPeriod": "month",
                "entity": "person",
                "name": "monthly_benefit",
                "isInputVariable": False,
                "defaultValue": None,
            },
            "person_id": {
                "definitionPeriod": "eternity",
                "entity": "person",
                "name": "person_id",
                "isInputVariable": True,
                "defaultValue": "",
            },
            "daily_value": {
                "definitionPeriod": "day",
                "entity": "person",
                "name": "daily_value",
                "isInputVariable": False,
                "defaultValue": None,
            },
        },
    }


def fake_countries():
    return SimpleNamespace(
        get=lambda country_id: SimpleNamespace(metadata=fake_country_metadata())
    )


def test_add_yearly_variables_fills_missing_year_month_and_eternity_values():
    household = {
        "people": {
            "you": {
                "age": {TEST_YEAR: 40},
                "employment_income": {TEST_YEAR: 10_000},
            }
        },
        "households": {"your household": {"members": ["you"]}},
    }

    result = add_yearly_variables(
        copy.deepcopy(household), "test", countries=fake_countries()
    )

    assert result["people"]["you"]["employment_income"] == {TEST_YEAR: 10_000}
    assert result["people"]["you"]["monthly_benefit"] == {TEST_YEAR: None}
    assert result["people"]["you"]["person_id"] == {TEST_YEAR: ""}
    assert "daily_value" not in result["people"]["you"]
    assert result["households"]["your household"]["household_net_income"] == {
        TEST_YEAR: None
    }


def test_add_yearly_variables_ignores_entities_missing_from_household():
    household = {
        "people": {
            "you": {
                "age": {TEST_YEAR: 40},
            }
        }
    }

    result = add_yearly_variables(
        copy.deepcopy(household), "test", countries=fake_countries()
    )

    assert "households" not in result
    assert result["people"]["you"]["employment_income"] == {TEST_YEAR: 0}
