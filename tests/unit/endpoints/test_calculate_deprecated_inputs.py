from flask import Flask
import pytest

from policyengine_api.endpoints import household as household_endpoint


class DummyCountry:
    def __init__(self):
        self.household = None
        self.policy = None

    def calculate(self, household, policy):
        self.household = household
        self.policy = policy
        return {"household": household, "policy": policy}


@pytest.fixture
def calculate_client(monkeypatch):
    country = DummyCountry()
    monkeypatch.setattr(
        household_endpoint,
        "get_countries",
        lambda: {"us": country},
    )

    app = Flask(__name__)
    app.add_url_rule(
        "/<country_id>/calculate",
        "calculate",
        household_endpoint.get_calculate,
        methods=["POST"],
    )
    return app.test_client(), country


def test__calculate__drops_deprecated_input_with_warning(calculate_client):
    client, country = calculate_client
    household = {
        "people": {
            "you": {
                "age": {"2025": 49},
                "medical_out_of_pocket_expenses": {"2025": 0},
            }
        }
    }

    response = client.post("/us/calculate", json={"household": household})

    assert response.status_code == 200
    payload = response.get_json()
    assert "medical_out_of_pocket_expenses" not in country.household["people"]["you"]
    assert country.household["people"]["you"]["age"] == {"2025": 49}
    assert payload["result"]["household"] == country.household
    assert any(
        "medical_out_of_pocket_expenses" in warning
        and "people/you" in warning
        and "deprecated" in warning.lower()
        for warning in payload["warnings"]
    )
    assert "medical_out_of_pocket_expenses" in household["people"]["you"]


def test__calculate__drops_deprecated_axis_with_warning(calculate_client):
    client, country = calculate_client
    household = {
        "people": {"you": {"age": {"2025": 49}}},
        "axes": [
            [
                {
                    "name": "medical_out_of_pocket_expenses",
                    "period": "2025",
                    "min": 0,
                    "max": 100,
                    "count": 2,
                },
                {
                    "name": "employment_income",
                    "period": "2025",
                    "min": 0,
                    "max": 100,
                    "count": 2,
                },
            ]
        ],
    }

    response = client.post("/us/calculate", json={"household": household})

    assert response.status_code == 200
    payload = response.get_json()
    assert country.household["axes"] == [
        [
            {
                "name": "employment_income",
                "period": "2025",
                "min": 0,
                "max": 100,
                "count": 2,
            }
        ]
    ]
    assert any(
        "medical_out_of_pocket_expenses" in warning and "axes[0][0].name" in warning
        for warning in payload["warnings"]
    )


def test__calculate__omits_warnings_without_deprecated_input(calculate_client):
    client, country = calculate_client
    household = {
        "people": {
            "you": {
                "age": {"2025": 49},
            }
        }
    }

    response = client.post("/us/calculate", json={"household": household})

    assert response.status_code == 200
    payload = response.get_json()
    assert "warnings" not in payload
    assert country.household == household


def test__calculate_full__drops_deprecated_input_after_add_missing(monkeypatch):
    country = DummyCountry()
    monkeypatch.setattr(
        household_endpoint,
        "get_countries",
        lambda: {"us": country},
    )
    monkeypatch.setattr(
        household_endpoint,
        "add_yearly_variables",
        lambda household, country_id: {
            **household,
            "people": {
                **household["people"],
                "you": {
                    **household["people"]["you"],
                    "employment_income": {"2025": None},
                },
            },
        },
    )

    app = Flask(__name__)

    def calculate_full(country_id):
        return household_endpoint.get_calculate(country_id, add_missing=True)

    app.add_url_rule(
        "/<country_id>/calculate-full",
        "calculate_full",
        calculate_full,
        methods=["POST"],
    )
    client = app.test_client()
    household = {
        "people": {
            "you": {
                "age": {"2025": 49},
                "medical_out_of_pocket_expenses": {"2025": 0},
            }
        }
    }

    response = client.post("/us/calculate-full", json={"household": household})

    assert response.status_code == 200
    payload = response.get_json()
    assert "medical_out_of_pocket_expenses" not in country.household["people"]["you"]
    assert country.household["people"]["you"]["employment_income"] == {"2025": None}
    assert any(
        "medical_out_of_pocket_expenses" in warning and "deprecated" in warning.lower()
        for warning in payload["warnings"]
    )
