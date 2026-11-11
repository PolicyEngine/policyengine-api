"""Which policies a household calculation refuses before it copies the model.

A household calculation converts each policy value to the type of its
parameter's earliest value (``PolicyEngineCountry._normalize_reform_values``)
and the country model then reads each period key: policyengine-core's
``Reform.from_dict`` for the US, policyengine-uk's ``dated_reforms`` for the
UK. The check refuses what that conversion or both readers fail on, and
accepts whatever one of them reads.
"""

from __future__ import annotations

import math

import pytest
from policyengine_core.parameters import Parameter

from policyengine_api.country import COUNTRIES
from policyengine_api.utils.household_policy_validation import (
    find_unreadable_policy_inputs,
    is_readable_period_key,
    reform_value_type,
)

PERIOD = "2026-01-01.2026-12-31"
US_METADATA = COUNTRIES["us"].metadata
# The earliest value of each is an int, a bool and a list.
NUMBER_PARAMETER = "gov.irs.credits.ctc.amount.base[0].amount"
BOOLEAN_PARAMETER = "gov.contrib.states.mt.ctc.in_effect"
LIST_PARAMETER = "gov.aca.ineligible_immigration_statuses"
# Parameters whose earliest value is a number, a bool and a list, in each model.
SAMPLE_PARAMETERS = {
    "us": (NUMBER_PARAMETER, BOOLEAN_PARAMETER, LIST_PARAMETER),
    "uk": (
        "gov.hmrc.income_tax.rates.uk[0].rate",
        "gov.contrib.abolish_council_tax",
        "gov.dfe.extended_childcare_entitlement.income.countable_sources",
    ),
}
SAMPLE_VALUES = [
    3000,
    0.25,
    "2500",
    " 2500 ",
    "1_000",
    "Infinity",
    "-Infinity",
    "inf",
    "nan",
    float("nan"),
    float("inf"),
    True,
    False,
    None,
    [],
    ["DACA"],
    [3000],
    {},
    {"a": 1},
    "abc",
    "",
    10**400,
]


def _entries(policy: object) -> list[dict]:
    return [
        entry.to_dict() for entry in find_unreadable_policy_inputs(policy, US_METADATA)
    ]


@pytest.mark.parametrize(
    "policy",
    [None, {}, False, 0, "", []],
    ids=["null", "empty-object", "false", "zero", "empty-text", "empty-list"],
)
def test_an_empty_or_null_policy_is_read_as_no_policy(policy):
    assert _entries(policy) == []


@pytest.mark.parametrize(
    ("policy", "received"),
    [(5, "5"), (True, "true"), ("abc", '"abc"'), ([{}], "[{}]")],
    ids=["number", "true", "text", "list"],
)
def test_a_policy_that_is_not_an_object_is_refused(policy, received):
    assert _entries(policy) == [
        {
            "type": "policy",
            "name": "policy",
            "path": "policy",
            "message": (
                "`policy` must be an object of parameter paths, each set to an "
                f"object of period keys and values, but it is {received}."
            ),
        }
    ]


@pytest.mark.parametrize(
    "parameter_value",
    [True, 3000, None, [3000], "abc"],
    ids=["true", "number", "null", "list", "text"],
)
def test_a_parameter_set_to_anything_but_an_object_is_refused(parameter_value):
    entries = _entries({NUMBER_PARAMETER: parameter_value})

    assert [(entry["type"], entry["name"], entry["path"]) for entry in entries] == [
        ("policy_period", NUMBER_PARAMETER, f"policy.{NUMBER_PARAMETER}")
    ]


def test_a_parameter_set_to_an_empty_object_changes_nothing_and_is_accepted():
    assert _entries({NUMBER_PARAMETER: {}}) == []


@pytest.mark.parametrize(
    "value",
    [3000, 0.25, "2500", " 2500 ", "Infinity", "-Infinity", True, float("inf")],
    ids=[
        "int",
        "float",
        "text",
        "padded-text",
        "infinity",
        "minus-infinity",
        "true",
        "float-infinity",
    ],
)
def test_a_number_parameter_accepts_what_converts_to_a_number(value):
    assert _entries({NUMBER_PARAMETER: {PERIOD: value}}) == []


@pytest.mark.parametrize(
    ("value", "received"),
    [
        ("abc", '"abc"'),
        ("", '""'),
        (None, "null"),
        ([3000], "[3000]"),
        ({}, "{}"),
        (10**400, "a number"),
    ],
    ids=["text", "empty-text", "null", "list", "object", "too-large"],
)
def test_a_number_parameter_refuses_what_does_not_convert(value, received):
    path = f"policy.{NUMBER_PARAMETER}.{PERIOD}"

    assert _entries({NUMBER_PARAMETER: {PERIOD: value}}) == [
        {
            "type": "policy_value",
            "name": NUMBER_PARAMETER,
            "path": path,
            "message": (
                f"Value at `{path}` must be a number, or text that reads as one "
                f'such as "Infinity", but it is {received}.'
            ),
        }
    ]


@pytest.mark.parametrize(
    "value",
    [True, False, 1, 0, "1", None, [], "abc"],
    ids=["true", "false", "one", "zero", "text-one", "null", "list", "text"],
)
def test_a_boolean_parameter_converts_every_value(value):
    # bool() converts anything, so nothing fails for a boolean parameter.
    assert _entries({BOOLEAN_PARAMETER: {PERIOD: value}}) == []


@pytest.mark.parametrize(
    "value",
    [["DACA"], [], "abc", {}],
    ids=["list", "empty-list", "text", "object"],
)
def test_a_list_parameter_accepts_what_list_converts(value):
    # list() reads text as its characters and an object as its keys.
    assert _entries({LIST_PARAMETER: {PERIOD: value}}) == []


@pytest.mark.parametrize(
    ("value", "received"),
    [(1, "1"), (None, "null"), (True, "true")],
    ids=["number", "null", "true"],
)
def test_a_list_parameter_refuses_what_list_cannot_convert(value, received):
    path = f"policy.{LIST_PARAMETER}.{PERIOD}"

    assert _entries({LIST_PARAMETER: {PERIOD: value}}) == [
        {
            "type": "policy_value",
            "name": LIST_PARAMETER,
            "path": path,
            "message": f"Value at `{path}` must be a list, but it is {received}.",
        }
    ]


def test_a_parameter_without_recorded_values_is_not_checked_for_its_values():
    metadata = {"parameters": {"gov.example": {"type": "parameter"}}}

    policy = {"gov.example": {PERIOD: "abc"}}

    assert find_unreadable_policy_inputs(policy, metadata) == []


def test_a_parameter_whose_earliest_value_is_null_is_left_to_the_calculation():
    # The calculation can convert no value for it (type(None) takes no
    # argument), but that is the calculation's failure, not the request's.
    metadata = COUNTRIES["uk"].metadata
    parameter = "gov.hmrc.income_tax.rates.scotland.rates[0].threshold"

    assert find_unreadable_policy_inputs({parameter: {PERIOD: 1000}}, metadata) == []


def test_every_problem_is_reported_in_policy_order_with_a_key_before_its_value():
    entries = _entries(
        {
            LIST_PARAMETER: {PERIOD: 1},
            NUMBER_PARAMETER: {"2026-13-01": None, PERIOD: 3000},
            BOOLEAN_PARAMETER: True,
        }
    )

    assert [entry["path"] for entry in entries] == [
        f"policy.{LIST_PARAMETER}.{PERIOD}",
        f"policy.{NUMBER_PARAMETER}.2026-13-01",
        f"policy.{NUMBER_PARAMETER}.2026-13-01",
        f"policy.{BOOLEAN_PARAMETER}",
    ]
    assert [entry["type"] for entry in entries] == [
        "policy_value",
        "policy_period",
        "policy_value",
        "policy_period",
    ]


# Each key with what policyengine-core's Reform.from_dict (US) and
# policyengine-uk's reform reader (UK) did with it, as checked against the
# installed models through a household calculation.
READABLE_PERIOD_KEYS = {
    "2026-01-01.2026-12-31": "both",
    "2026-12-31.2026-12-31": "both",
    "2026-01-01": "both",
    "2026": "both",
    "2026-01": "both",
    "2026.2027": "both",
    "year:2026:5": "both",
    "year:2026": "both",
    "month:2026-01:3": "both",
    "ETERNITY": "US",
    "2026-1-1": "UK",
}
UNREADABLE_PERIOD_KEYS = {
    "2026-02-30.2026-12-31": "no such day",
    "2026-13-01.2026-12-31": "no such month",
    "2026-1-1.2026-12-31": "unpadded date in a range",
    "0000-01-01.2026-12-31": "year 0",
    "2026-12-31.2026-01-01": "ends before it starts",
    "2026-01-01.2026-12-31.2027-01-01": "three dates",
    "2026-01-01.": "no end",
    ".2026-12-31": "no start",
    "2026-01-01 .2026-12-31": "space",
    "1.5": "not dates",
    "": "empty",
    "abc": "text",
    "eternity": "lowercase eternity",
    "2026-02-30": "no such day",
    "2026-00-01": "month 0",
    "02026-01-01": "five-digit year",
    "2026-01-01T00:00": "time of day",
    "year:abc:1": "text in a period",
    "month:2026-13:1": "no such month in a period",
    "day:2026-02-30:1": "no such day in a period",
}


@pytest.mark.parametrize("period_key", list(READABLE_PERIOD_KEYS))
def test_a_period_key_one_model_reads_is_accepted(period_key):
    assert is_readable_period_key(period_key)


@pytest.mark.parametrize("period_key", list(UNREADABLE_PERIOD_KEYS))
def test_a_period_key_neither_model_reads_is_refused(period_key):
    assert not is_readable_period_key(period_key)


def test_an_unreadable_period_key_is_reported_with_its_path():
    period_key = "2026-12-31.2026-01-01"
    path = f"policy.{NUMBER_PARAMETER}.{period_key}"

    assert _entries({NUMBER_PARAMETER: {period_key: 3000}}) == [
        {
            "type": "policy_period",
            "name": NUMBER_PARAMETER,
            "path": path,
            "message": (
                f"Period key `{period_key}` at `{path}` must be a range of two "
                "dates (YYYY-MM-DD.YYYY-MM-DD) whose start is no later than its "
                "end, or one period such as 2026, 2026-01-01 or year:2026:1."
            ),
        }
    ]


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_the_conversion_type_read_from_metadata_is_the_models(country_id):
    """Metadata lists each parameter's values latest first, like ``values_list``.

    So the last one is the earliest value, whose type the calculation converts
    to; an infinity is written as text, and a null earliest value is unknown.
    """
    country = COUNTRIES[country_id]
    model_parameters = {
        parameter.name: parameter
        for parameter in country.tax_benefit_system.parameters.get_descendants()
        if isinstance(parameter, Parameter)
    }
    mismatches = []
    for parameter_name, parameter_metadata in country.metadata["parameters"].items():
        if parameter_metadata.get("type") != "parameter":
            continue
        earliest_value = model_parameters[parameter_name].values_list[-1].value
        expected = None if earliest_value is None else type(earliest_value)
        if expected is int:
            expected = float
        if reform_value_type(parameter_metadata) is not expected:
            mismatches.append(parameter_name)

    assert mismatches == []


@pytest.mark.parametrize(
    ("country_id", "parameter_name"),
    [
        (country_id, parameter_name)
        for country_id, parameter_names in SAMPLE_PARAMETERS.items()
        for parameter_name in parameter_names
    ],
)
def test_a_value_is_refused_exactly_when_the_models_conversion_fails(
    country_id,
    parameter_name,
):
    country = COUNTRIES[country_id]
    disagreements = []
    for value in SAMPLE_VALUES:
        policy = {parameter_name: {PERIOD: value}}
        refused = bool(find_unreadable_policy_inputs(policy, country.metadata))
        try:
            country._normalize_reform_values(policy, country.tax_benefit_system)
        except (TypeError, ValueError, OverflowError):
            conversion_failed = True
        else:
            conversion_failed = False
        if refused is not conversion_failed:
            disagreements.append(value)

    assert [
        "nan" if isinstance(value, float) and math.isnan(value) else value
        for value in disagreements
    ] == []
