from flask import Flask
import pytest
from policyengine_core.errors import SituationParsingError

from policyengine_api.endpoints import household as household_endpoint

from .test_calculate_deprecated_inputs import DummyCountry

HOUSEHOLD = {
    "people": {
        "you": {
            "age": {"2026": 40},
            "employment_income": {"2026": 30_000},
        }
    }
}


class ParsingErrorCountry(DummyCountry):
    def calculate(self, household, policy):
        raise SituationParsingError(
            ["people", "you", "employment_income", "2026"],
            "Can't deal with value: expected type number, received '{}'.",
        )


class CrashingCountry(DummyCountry):
    def calculate(self, household, policy):
        raise RuntimeError("engine exploded")


def make_client(monkeypatch, country, add_missing=False):
    monkeypatch.setattr(
        household_endpoint,
        "get_countries",
        lambda: {"us": country},
    )
    app = Flask(__name__)
    if add_missing:
        monkeypatch.setattr(
            household_endpoint,
            "add_yearly_variables",
            lambda household, country_id: household,
        )

        def handler(country_id):
            return household_endpoint.get_calculate(
                country_id, add_missing=True
            )

        app.add_url_rule(
            "/<country_id>/calculate-full",
            "calculate_full",
            handler,
            methods=["POST"],
        )
    else:
        app.add_url_rule(
            "/<country_id>/calculate",
            "calculate",
            household_endpoint.get_calculate,
            methods=["POST"],
        )
    return app.test_client()


def test__calculate__returns_400_on_situation_parsing_error(monkeypatch):
    client = make_client(monkeypatch, ParsingErrorCountry())

    response = client.post("/us/calculate", json={"household": HOUSEHOLD})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["result"] is None
    assert payload["message"].startswith("Invalid household payload")


def test__calculate_full__returns_400_on_situation_parsing_error(monkeypatch):
    client = make_client(monkeypatch, ParsingErrorCountry(), add_missing=True)

    response = client.post("/us/calculate-full", json={"household": HOUSEHOLD})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["result"] is None
    assert payload["message"].startswith("Invalid household payload")


def test__calculate__returns_500_on_unexpected_error(monkeypatch):
    client = make_client(monkeypatch, CrashingCountry())

    response = client.post("/us/calculate", json={"household": HOUSEHOLD})

    assert response.status_code == 500
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "engine exploded" in payload["message"]
