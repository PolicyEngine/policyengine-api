"""A household calculation refuses, with a 400, a policy the calculation can't read.

Telemetry issue #4275: a ``policy`` that isn't an object, a parameter set to
``true`` instead of an object of period keys, and values such as ``"abc"``,
``null`` or a list each failed while the calculation converted the policy's
values, after the model's tax-benefit system had been copied, and answered 500
with a record at ERROR.

The stand-in country has the loaded US model's metadata. It parses a situation
by converting the policy's values with the loaded model's own conversion
(``PolicyEngineCountry._normalize_reform_values``) and reading each parameter's
period keys with policyengine-core's ``Reform.from_dict``, as the US model
does, so a policy the check lets through fails as it does in production. It
never copies the tax-benefit system or builds a simulation.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, NamedTuple
from unittest.mock import patch

import pytest
from flask import Flask
from policyengine_core.parameters import ParameterNode
from policyengine_core.reforms import Reform

from policyengine_api.country import COUNTRIES
from policyengine_api.extensions import cache
from policyengine_api.routes import household_routes
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
)
from policyengine_api.utils.policy_data_validation import PERIOD_OBJECT_REQUIREMENT

from .test_calculate_deprecated_inputs import DummyCountry

if TYPE_CHECKING:
    from flask.testing import FlaskClient

HOUSEHOLD = {"people": {"you": {"age": {"2026": 40}}}}
PERIOD = "2026-01-01.2026-12-31"
# The earliest value of each is an int, a bool and a list.
NUMBER_PARAMETER = "gov.irs.credits.ctc.amount.base[0].amount"
BOOLEAN_PARAMETER = "gov.contrib.states.mt.ctc.in_effect"
LIST_PARAMETER = "gov.aca.ineligible_immigration_statuses"
ENDPOINTS = ["calculate", "calculate-full"]
NUMBER_REQUIREMENT = 'a number, or text that reads as one such as "Infinity"'
PERIOD_KEY_REQUIREMENT = (
    "a date range (YYYY-MM-DD.YYYY-MM-DD) or one period, such as 2026, "
    "2026-01-01 or year:2026:1, of real calendar dates before 9999-12-31"
)


class ReformConvertingCountry(DummyCountry):
    """The loaded US model's metadata and value conversion, without a simulation."""

    def __init__(self) -> None:
        super().__init__()
        self.model = COUNTRIES["us"]
        self.metadata = self.model.metadata
        self.converted_policies: list[object] = []

    def prepare_calculation(self, household, policy, **_kwargs):
        if policy:
            # Reads the parameters' values without copying or changing them.
            converted = self.model._normalize_reform_values(
                policy, self.model.tax_benefit_system
            )
            for period_values in converted.values():
                # How Reform.from_dict reads a key doesn't depend on the
                # parameter, so each parameter's keys go onto one of its own.
                parameters = ParameterNode(
                    "", data={"p": {"values": {"2020-01-01": 1.0}}}
                )
                Reform.from_dict({"p": period_values}).apply(
                    SimpleNamespace(parameters=parameters)
                )
        self.converted_policies.append(policy)
        return {"household": household}


class CalculationHarness(NamedTuple):
    """A client of the household routes and the stand-in country they use."""

    client: FlaskClient
    country: ReformConvertingCountry


@pytest.fixture
def harness(monkeypatch) -> CalculationHarness:
    country = ReformConvertingCountry()
    monkeypatch.setattr(
        household_routes,
        "household_calculation_service",
        HouseholdCalculationService(country_provider=lambda: {"us": country}),
    )
    # calculate-full adds the variables a household leaves out; these tests
    # are about the policy.
    monkeypatch.setattr(
        "policyengine_api.services.household_calculation_service.add_yearly_variables",
        lambda household, _country_id, _countries=None: household,
    )
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="NullCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    return CalculationHarness(app.test_client(), country)


def _value_entry(value_text: str) -> dict:
    path = f"policy.{NUMBER_PARAMETER}.{PERIOD}"
    return {
        "type": "policy_value",
        "name": NUMBER_PARAMETER,
        "path": path,
        "message": (
            f"Value at `{path}` must be {NUMBER_REQUIREMENT}, but it is {value_text}."
        ),
    }


UNREADABLE_PERIOD_KEY = "2026-02-30.2026-12-31"
OPEN_ENDED_PERIOD_KEY = "2026-01-01.9999-12-31"


def _period_key_entry(period_key: str) -> dict:
    path = f"policy.{NUMBER_PARAMETER}.{period_key}"
    return {
        "type": "policy_period",
        "name": NUMBER_PARAMETER,
        "path": path,
        "message": (
            f"Period key `{period_key}` at `{path}` must be {PERIOD_KEY_REQUIREMENT}."
        ),
    }


REFUSED_POLICIES = [
    pytest.param(
        5,
        {
            "type": "policy",
            "name": "policy",
            "path": "policy",
            "message": (
                "`policy` must be an object of parameter paths, each set to an "
                "object of period keys and values, but it is 5."
            ),
        },
        id="policy-is-a-number",
    ),
    pytest.param(
        {NUMBER_PARAMETER: True},
        {
            "type": "policy_period",
            "name": NUMBER_PARAMETER,
            "path": f"policy.{NUMBER_PARAMETER}",
            "message": (
                f"`policy.{NUMBER_PARAMETER}` must be {PERIOD_OBJECT_REQUIREMENT}, "
                "but it is true."
            ),
        },
        id="parameter-is-true",
    ),
    pytest.param(
        {NUMBER_PARAMETER: {PERIOD: "abc"}},
        _value_entry('"abc"'),
        id="value-is-text",
    ),
    pytest.param(
        {NUMBER_PARAMETER: {PERIOD: None}},
        _value_entry("null"),
        id="value-is-null",
    ),
    pytest.param(
        {NUMBER_PARAMETER: {PERIOD: [3000]}},
        _value_entry("[3000]"),
        id="value-is-a-list",
    ),
    pytest.param(
        {NUMBER_PARAMETER: {UNREADABLE_PERIOD_KEY: 3000}},
        _period_key_entry(UNREADABLE_PERIOD_KEY),
        id="period-key-is-not-a-date",
    ),
    pytest.param(
        {NUMBER_PARAMETER: {OPEN_ENDED_PERIOD_KEY: 3000}},
        _period_key_entry(OPEN_ENDED_PERIOD_KEY),
        id="period-key-ends-on-the-last-date",
    ),
]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(("policy", "expected_entry"), REFUSED_POLICIES)
def test_calculation_refuses_a_policy_it_cannot_read(
    harness,
    caplog,
    endpoint,
    policy,
    expected_entry,
):
    with patch.object(
        household_routes,
        "start_observability_id",
    ) as start_observability_id:
        response = harness.client.post(
            f"/us/{endpoint}",
            json={"household": HOUSEHOLD, "policy": policy},
        )

    error_records = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
    ]
    assert (response.status_code, error_records) == (400, [])
    body = response.get_json()
    assert body["status"] == "error"
    assert body["result"] is None
    assert body["errors"] == [expected_entry]
    assert body["message"] == (
        f"Invalid calculate input(s): {expected_entry['message']}"
    )
    # Refused before the situation is parsed, where the model's tax-benefit
    # system is copied, and before the request is accepted.
    assert harness.country.converted_policies == []
    start_observability_id.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    "policy",
    [
        pytest.param(
            {
                NUMBER_PARAMETER: {
                    PERIOD: 3000,
                    "2027-01-01": "Infinity",
                    "2028": "-Infinity",
                    "2029-01-01.2029-12-31": "2500",
                    "year:2030:2": 2600,
                    "ETERNITY": 2000,
                },
                BOOLEAN_PARAMETER: {PERIOD: True},
                LIST_PARAMETER: {PERIOD: ["DACA"]},
            },
            id="values-the-model-reads",
        ),
        pytest.param({}, id="empty-policy"),
        pytest.param(None, id="null-policy"),
    ],
)
def test_calculation_accepts_a_policy_it_can_read(
    harness,
    caplog,
    endpoint,
    policy,
):
    response = harness.client.post(
        f"/us/{endpoint}",
        json={"household": HOUSEHOLD, "policy": policy},
    )

    error_records = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
    ]
    assert (response.status_code, error_records) == (200, [])
    assert harness.country.converted_policies == [policy]
    assert response.get_json()["result"]["policy"] == policy
