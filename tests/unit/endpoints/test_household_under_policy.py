import copy
import importlib
import json
import sys
import types
from types import SimpleNamespace

import pytest
from flask import Response

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS


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
        "tax_due": {
            "name": "tax_due",
            "definitionPeriod": "year",
            "entity": "tax_unit",
            "isInputVariable": False,
            "defaultValue": 0,
        },
    },
    "entities": {
        "person": {"plural": "people"},
        "tax_unit": {"plural": "tax_units"},
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
    "tax_units": {"tax_unit": {"members": ["you", "partner"]}},
}


class FakeCountry:
    def __init__(self):
        self.metadata = copy.deepcopy(FAKE_METADATA)
        self.calls = []

    def calculate(self, household_json, policy_json, household_id, policy_id):
        self.calls.append(
            {
                "household_json": household_json,
                "policy_json": policy_json,
                "household_id": household_id,
                "policy_id": policy_id,
            }
        )
        return {
            "people": {
                "you": {
                    "age": {"2025": 40},
                    "employment_income": {"2025": 30000},
                },
                "partner": {
                    "age": {"2025": 40},
                    "employment_income": {"2025": 0},
                },
            },
            "tax_units": {
                "tax_unit": {
                    "tax_due": {"2025": 123},
                }
            },
        }


@pytest.fixture
def household_module(monkeypatch, test_db):
    fake_country = FakeCountry()
    fake_country_module = types.ModuleType("policyengine_api.country")
    fake_country_module.COUNTRIES = SimpleNamespace(
        get=lambda country_id: fake_country
    )

    monkeypatch.setitem(sys.modules, "policyengine_api.country", fake_country_module)
    sys.modules.pop("policyengine_api.endpoints.household", None)

    module = importlib.import_module("policyengine_api.endpoints.household")
    monkeypatch.setattr(module, "database", test_db)
    monkeypatch.setattr(module, "local_database", test_db)

    return module, fake_country


def _insert_household(test_db, household_id: int, country_id: str = "us") -> None:
    test_db.query(
        """INSERT INTO household
        (id, country_id, label, api_version, household_json, household_hash)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            household_id,
            country_id,
            "Test household",
            COUNTRY_PACKAGE_VERSIONS[country_id],
            json.dumps(BASE_HOUSEHOLD),
            "test-household-hash",
        ),
    )


def _insert_policy(test_db, policy_id: int = 2, country_id: str = "us") -> None:
    test_db.query(
        """INSERT INTO policy
        (id, country_id, label, api_version, policy_json, policy_hash)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            policy_id,
            country_id,
            "Current law",
            COUNTRY_PACKAGE_VERSIONS[country_id],
            json.dumps({}),
            "test-policy-hash",
        ),
    )


def test_get_household_under_policy_returns_result_and_persists_cache(
    test_db, household_module
):
    module, fake_country = household_module
    household_id = -1001
    policy_id = "2"
    _insert_household(test_db, household_id)
    _insert_policy(test_db, int(policy_id))

    result = module.get_household_under_policy("us", str(household_id), policy_id)

    assert result["status"] == "ok"
    assert result["result"]["tax_units"]["tax_unit"]["tax_due"] == {"2025": 123}
    assert len(fake_country.calls) == 1
    assert fake_country.calls[0]["household_json"]["people"]["partner"][
        "employment_income"
    ] == {"2025": 0}

    cached_row = test_db.query(
        """SELECT computed_household_json
        FROM computed_household
        WHERE household_id = ? AND policy_id = ? AND country_id = ?""",
        (household_id, int(policy_id), "us"),
    ).fetchone()

    assert cached_row is not None


def test_get_household_under_policy_uses_cached_result_without_recalculation(
    test_db, household_module
):
    module, fake_country = household_module
    household_id = -1002
    policy_id = "2"
    _insert_household(test_db, household_id)
    _insert_policy(test_db, int(policy_id))

    first = module.get_household_under_policy("us", str(household_id), policy_id)
    second = module.get_household_under_policy("us", str(household_id), policy_id)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert len(fake_country.calls) == 1
    assert second["result"] == first["result"]


def test_get_household_under_policy_returns_404_for_missing_household(
    household_module,
):
    module, _ = household_module

    response = module.get_household_under_policy("us", "-9999", "2")

    assert isinstance(response, Response)
    assert response.status_code == 404
    payload = json.loads(response.get_data(as_text=True))
    assert payload["status"] == "error"
    assert "not found" in payload["message"].lower()


def test_get_household_under_policy_returns_404_for_missing_policy(
    test_db, household_module
):
    module, _ = household_module
    household_id = -1003
    _insert_household(test_db, household_id)

    response = module.get_household_under_policy("us", str(household_id), "999")

    assert isinstance(response, Response)
    assert response.status_code == 404
    payload = json.loads(response.get_data(as_text=True))
    assert payload["status"] == "error"
    assert "policy #999 not found" in payload["message"].lower()
