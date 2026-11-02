"""A new v1 policy may hold only period keys and values that simulations can read.

A period key is one date (YYYY-MM-DD) or an inclusive date range
(YYYY-MM-DD.YYYY-MM-DD) of real calendar dates whose start is no later than its
end. A value is a finite number, a boolean, null, a list, or the string
"Infinity" or "-Infinity", which is how the Public API writes infinite values.
Re-saving a policy identical to a stored one returns the stored policy without
checking it.
"""

from __future__ import annotations

import json

import pytest
from flask import Flask
from sqlalchemy import select

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import Policy
from policyengine_api.routes.policy_routes import policy_bp
from policyengine_api.utils import hash_object
from tests.fixtures.policy_parameter_paths import POLICY_PERIOD

COUNTRY_IDS = ("us", "uk")

# Parameters in each installed country model: one that holds an amount, a
# threshold that can be set to infinity, a boolean switch and a list.
AMOUNT_PARAMETERS = {
    "us": "gov.irs.credits.ctc.amount.base[0].amount",
    "uk": "gov.hmrc.income_tax.allowances.personal_allowance.amount",
}
THRESHOLD_PARAMETERS = {
    "us": "gov.irs.credits.ctc.phase_out.threshold.JOINT",
    "uk": "gov.hmrc.income_tax.rates.uk[2].threshold",
}
SWITCH_PARAMETERS = {
    "us": "gov.irs.credits.ctc.refundable.fully_refundable",
    "uk": "gov.dfc.LHA.freeze",
}
LIST_PARAMETERS = {
    "us": "gov.aca.ineligible_coverage",
    "uk": "gov.dfe.extended_childcare_entitlement.income.countable_sources",
}

PERIOD_KEY_REQUIREMENT = (
    "must be a date (YYYY-MM-DD) or an inclusive date range "
    "(YYYY-MM-DD.YYYY-MM-DD) of real calendar dates whose start is no later "
    "than its end"
)
VALUE_REQUIREMENT = (
    "must be a finite number, a boolean, null, a list, "
    'or the string "Infinity" or "-Infinity"'
)
ENTRIES_MESSAGE_PREFIX = "Policy data contains invalid period keys or values: "

# Period keys the simulation cannot read, each set to a valid amount.
UNREADABLE_PERIOD_KEYS = {
    "bare year": "2024",
    "year, month and day joined by dots": "2029.1.1",
    "two bare years": "2025.2025",
    "unpadded month and day": "2027-4-6",
    "day the month does not have": "2026-02-30",
    "end before start": "2026-12-31.2026-01-01",
    "three dates": "2026-01-01.2026-06-30.2026-12-31",
    "range without an end": "2026-01-01.",
    "named period": "year:2026:1",
}

# Values the simulation cannot read, each set for a valid date range.
UNREADABLE_VALUES = {
    "wrapped value": {"value": 13000},
    "numeric string": "13000",
    "text": "thirteen thousand",
    "infinity in lower case": "inf",
    "NaN": float("nan"),
    "unquoted infinity": float("inf"),
}

# Period keys and values the simulation reads, with the parameter they set.
READABLE_ENTRIES = {
    "single date": (AMOUNT_PARAMETERS, "2026-01-01", 13000),
    "date range": (AMOUNT_PARAMETERS, POLICY_PERIOD, 13000),
    "one-day date range": (AMOUNT_PARAMETERS, "2026-01-01.2026-01-01", 13000),
    "leap day": (AMOUNT_PARAMETERS, "2028-02-29", 13000),
    "decimal": (AMOUNT_PARAMETERS, POLICY_PERIOD, 13000.5),
    "null": (AMOUNT_PARAMETERS, POLICY_PERIOD, None),
    "infinity": (THRESHOLD_PARAMETERS, POLICY_PERIOD, "Infinity"),
    "negative infinity": (THRESHOLD_PARAMETERS, POLICY_PERIOD, "-Infinity"),
    "true": (SWITCH_PARAMETERS, POLICY_PERIOD, True),
    "false": (SWITCH_PARAMETERS, POLICY_PERIOD, False),
    "list": (LIST_PARAMETERS, POLICY_PERIOD, []),
}


def _cases_for_each_country(shapes: dict) -> list:
    return [
        pytest.param(country_id, shape, id=f"{country_id}-{description}")
        for country_id in COUNTRY_IDS
        for description, shape in shapes.items()
    ]


@pytest.fixture(autouse=True)
def cloud_sql_only_writes(monkeypatch):
    monkeypatch.setenv("DB_WRITE_POLICY", "cloud_sql")


def _policy_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(policy_bp)
    return app.test_client()


def _stored_policies(orm_session_factory) -> list[Policy]:
    with orm_session_factory() as session:
        return list(session.scalars(select(Policy)))


def _period_key_error(parameter_path: str, period_key: str) -> dict:
    entry_path = f"data.{parameter_path}.{period_key}"
    return {
        "type": "policy_period",
        "name": parameter_path,
        "path": entry_path,
        "message": (
            f"Period key `{period_key}` at `{entry_path}` {PERIOD_KEY_REQUIREMENT}."
        ),
    }


def _value_error(parameter_path: str, period_key: str, received: str) -> dict:
    entry_path = f"data.{parameter_path}.{period_key}"
    return {
        "type": "policy_value",
        "name": parameter_path,
        "path": entry_path,
        "message": (
            f"Value at `{entry_path}` {VALUE_REQUIREMENT}, but it is {received}."
        ),
    }


def _path_error(parameter_path: str) -> dict:
    return {
        "type": "policy_parameter",
        "name": parameter_path,
        "path": f"data.{parameter_path}",
        "message": (
            f"Unrecognized policy parameter `{parameter_path}` at "
            f"`data.{parameter_path}`."
        ),
    }


def _assert_refused(response, expected_errors: list[dict], expected_message: str):
    assert response.status_code == 400
    assert response.mimetype == "application/json"
    body = response.get_json()
    assert body["status"] == "error"
    assert body["result"] is None
    assert body["errors"] == expected_errors
    assert body["message"] == expected_message


def _entries_message(expected_errors: list[dict]) -> str:
    return ENTRIES_MESSAGE_PREFIX + " ".join(
        error["message"] for error in expected_errors
    )


@pytest.mark.parametrize(
    ("country_id", "period_key"), _cases_for_each_country(UNREADABLE_PERIOD_KEYS)
)
def test_new_policy_with_an_unreadable_period_key_returns_400(
    orm_session_factory,
    country_id,
    period_key,
):
    parameter_path = AMOUNT_PARAMETERS[country_id]

    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"data": {parameter_path: {period_key: 13000}}},
    )

    expected_errors = [_period_key_error(parameter_path, period_key)]
    _assert_refused(response, expected_errors, _entries_message(expected_errors))
    assert _stored_policies(orm_session_factory) == []


@pytest.mark.parametrize(
    ("country_id", "value"), _cases_for_each_country(UNREADABLE_VALUES)
)
def test_new_policy_with_an_unreadable_value_returns_400(
    orm_session_factory,
    country_id,
    value,
):
    parameter_path = AMOUNT_PARAMETERS[country_id]

    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"data": {parameter_path: {POLICY_PERIOD: value}}},
    )

    expected_errors = [_value_error(parameter_path, POLICY_PERIOD, json.dumps(value))]
    _assert_refused(response, expected_errors, _entries_message(expected_errors))
    assert _stored_policies(orm_session_factory) == []


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_new_policy_setting_a_parameter_to_a_bare_value_returns_400(
    orm_session_factory,
    country_id,
):
    parameter_path = AMOUNT_PARAMETERS[country_id]

    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"data": {parameter_path: 13000}},
    )

    expected_errors = [
        {
            "type": "policy_period",
            "name": parameter_path,
            "path": f"data.{parameter_path}",
            "message": (
                f"`data.{parameter_path}` must be an object of period keys and "
                'values, such as {"2026-01-01.2026-12-31": 1}, but it is 13000.'
            ),
        }
    ]
    _assert_refused(response, expected_errors, _entries_message(expected_errors))
    assert _stored_policies(orm_session_factory) == []


def test_new_policy_with_bare_years_and_wrapped_values_lists_every_entry(
    orm_session_factory,
):
    parameter_path = AMOUNT_PARAMETERS["uk"]
    years = ["2024", "2025", "2026", "2027", "2028", "2029"]
    requested_policy = {parameter_path: {year: {"value": 13000} for year in years}}

    response = _policy_client().post("/uk/policy", json={"data": requested_policy})

    expected_errors = [
        error
        for year in years
        for error in (
            _period_key_error(parameter_path, year),
            _value_error(parameter_path, year, '{"value": 13000}'),
        )
    ]
    _assert_refused(response, expected_errors, _entries_message(expected_errors))
    assert _stored_policies(orm_session_factory) == []


def test_new_policy_400_lists_entries_by_parameter_path(orm_session_factory):
    rate_path = "gov.hmrc.income_tax.rates.uk[0].rate"
    amount_path = AMOUNT_PARAMETERS["uk"]
    requested_policy = {
        rate_path: {"2029": {"value": 0.21}},
        amount_path: {POLICY_PERIOD: 13000, "2025.2025": "13000"},
    }

    response = _policy_client().post("/uk/policy", json={"data": requested_policy})

    expected_errors = [
        _period_key_error(amount_path, "2025.2025"),
        _value_error(amount_path, "2025.2025", '"13000"'),
        _period_key_error(rate_path, "2029"),
        _value_error(rate_path, "2029", '{"value": 0.21}'),
    ]
    _assert_refused(response, expected_errors, _entries_message(expected_errors))
    assert _stored_policies(orm_session_factory) == []


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_new_policy_400_combines_unknown_paths_with_unreadable_entries(
    orm_session_factory,
    country_id,
):
    parameter_path = AMOUNT_PARAMETERS[country_id]
    requested_policy = {
        "gov.x": {POLICY_PERIOD: 1},
        parameter_path: {"2024": {"value": 13000}},
    }

    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"label": "Unknown path and bare year", "data": requested_policy},
    )

    entry_errors = [
        _period_key_error(parameter_path, "2024"),
        _value_error(parameter_path, "2024", '{"value": 13000}'),
    ]
    expected_message = (
        "Policy data contains keys that are not parameters in "
        f"policyengine-{country_id} {COUNTRY_PACKAGE_VERSIONS[country_id]}: gov.x. "
        + _entries_message(entry_errors)
    )
    _assert_refused(response, [_path_error("gov.x"), *entry_errors], expected_message)
    assert _stored_policies(orm_session_factory) == []


@pytest.mark.parametrize(
    ("country_id", "readable_entry"), _cases_for_each_country(READABLE_ENTRIES)
)
def test_new_policy_with_readable_period_keys_and_values_is_created(
    orm_session_factory,
    country_id,
    readable_entry,
):
    parameters_by_country, period_key, value = readable_entry
    requested_policy = {parameters_by_country[country_id]: {period_key: value}}

    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"data": requested_policy},
    )

    assert response.status_code == 201
    stored_policies = _stored_policies(orm_session_factory)
    assert [policy.id for policy in stored_policies] == [
        response.get_json()["result"]["policy_id"]
    ]
    assert stored_policies[0].policy_json == requested_policy


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_resaving_a_stored_policy_with_unreadable_entries_returns_it(
    orm_session_factory,
    country_id,
):
    requested_policy = {
        AMOUNT_PARAMETERS[country_id]: {
            "2024": {"value": 13000},
            "2029.1.1": "13000",
        }
    }
    with orm_session_factory.begin() as session:
        session.add(
            Policy(
                id=99009,
                country_id=country_id,
                label=None,
                api_version="2.151.0",
                policy_json=requested_policy,
                policy_hash=hash_object(requested_policy),
            )
        )

    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"data": requested_policy},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "message": "Policy already exists",
        "result": {"policy_id": 99009},
    }
    assert [policy.id for policy in _stored_policies(orm_session_factory)] == [99009]
