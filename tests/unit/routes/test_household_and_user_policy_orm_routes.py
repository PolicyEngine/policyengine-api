"""ORM integration behavior for household and saved-policy routes."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from sqlalchemy import select

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import (
    ComputedHousehold,
    Household,
    Policy,
    UserPolicy,
)
from policyengine_api.routes.household_routes import get_household_under_policy
from policyengine_api.routes.policy_routes import (
    get_user_policy,
    set_user_policy,
    update_user_policy,
)
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
)


def test_household_under_policy_returns_cached_json_object(orm_session_factory):
    stored_result = {"people": {"you": {"net_income": {"2026": 42}}}}
    with orm_session_factory.begin() as session:
        session.add(
            ComputedHousehold(
                household_id=1,
                policy_id=2,
                country_id="us",
                api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                computed_household_json=stored_result,
                status="complete",
            )
        )

    response = get_household_under_policy("us", "1", "2")

    assert response["result"] == {"people": {"you": {"net_income": {"2026": 42}}}}


def test_household_under_policy_calculates_and_caches_json_as_an_object(
    orm_session_factory,
):
    with orm_session_factory.begin() as session:
        session.add_all(
            [
                Household(
                    id=1,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    household_json={"people": {"you": {}}},
                    household_hash="household-hash",
                ),
                Policy(
                    id=2,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    policy_json={"gov.example.parameter": 1},
                    policy_hash="policy-hash",
                ),
            ]
        )
    calculated = {"people": {"you": {"net_income": {"2026": 42}}}}
    country = SimpleNamespace(
        calculate=Mock(return_value=calculated),
        metadata={
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
            "parameters": {"gov.example.parameter": {}},
        },
    )
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        local_session_factory=orm_session_factory,
        country_provider=lambda: {"us": country},
    )

    with patch(
        "policyengine_api.routes.household_routes.household_calculation_service",
        service,
    ):
        response = get_household_under_policy("us", "1", "2")

    assert response["result"] == calculated
    country.calculate.assert_called_once_with(
        {"people": {"you": {}}},
        {"gov.example.parameter": 1},
    )
    with orm_session_factory() as session:
        cached = session.scalar(select(ComputedHousehold))
        assert cached.computed_household_json == calculated


def test_user_policy_endpoints_round_trip_through_orm_session_factory(
    orm_session_factory,
):
    app = Flask(__name__)
    payload = {
        "reform_label": "Reform",
        "reform_id": 2,
        "baseline_label": "Current law",
        "baseline_id": 1,
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "dataset": "default",
        "number_of_provisions": 3,
        "api_version": "1",
        "added_date": 1,
        "updated_date": 1,
        "budgetary_impact": None,
        "type": None,
    }

    with app.test_request_context(json=payload):
        created = set_user_policy("us")
    listed = get_user_policy("us", "auth0|one")
    with app.test_request_context(json={"id": 1, "reform_label": "Updated"}):
        updated = update_user_policy("us")

    assert created.status_code == 201
    assert created.get_json()["result"]["dataset"] == "default"
    assert listed["result"][0]["reform_label"] == "Reform"
    assert updated.status_code == 200
    with orm_session_factory() as session:
        assert session.get(UserPolicy, 1).reform_label == "Updated"
