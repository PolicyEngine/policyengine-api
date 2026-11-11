"""Which policies a household calculation refuses before it copies the model.

A household calculation converts each policy value to the type of its
parameter's earliest value (``PolicyEngineCountry._normalize_reform_values``)
and the country model then reads each period key: policyengine-core's
``Reform.from_dict`` for the US, policyengine-uk's ``dated_reforms`` for the
UK. The check refuses what that conversion, or the reader of the country
being calculated, fails on, and accepts what they read.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from policyengine_core import periods
from policyengine_core.parameters import Parameter, ParameterNode
from policyengine_core.reforms import Reform
from policyengine_uk.utils.dated_reforms import read_reform_dict

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
        entry.to_dict()
        for entry in find_unreadable_policy_inputs(policy, US_METADATA, "us")
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

    assert find_unreadable_policy_inputs(policy, metadata, "us") == []


def test_a_parameter_whose_earliest_value_is_null_is_left_to_the_calculation():
    # The calculation can convert no value for it (type(None) takes no
    # argument), but that is the calculation's failure, not the request's.
    metadata = COUNTRIES["uk"].metadata
    parameter = "gov.hmrc.income_tax.rates.scotland.rates[0].threshold"

    policy = {parameter: {PERIOD: 1000}}

    assert find_unreadable_policy_inputs(policy, metadata, "uk") == []


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


# What each model's reader does with a period key, from household
# calculations run with the installed models. The US model reads keys with
# policyengine-core's Reform.from_dict, the UK model with policyengine-uk's
# dated_reforms; the reader tests below check each list against them.
COMMON_READABLE_KEYS = [
    "2026-01-01.2026-12-31",
    "2026-12-31.2026-12-31",
    "2026.2027",
    "2026-01.2026-06",
    "2026-01-01",
    "2026",
    "2026-01",
    "year:2026:5",
    "year:2026",
    "month:2026-01:3",
    "year:2026:-1",
    "\uff12\uff10\uff12\uff16.\uff12\uff10\uff12\uff17",
    "2026-01-01.2026-12-31\n",
]
COMMON_UNREADABLE_KEYS = [
    "\u00b2",
    "\u2460",
    "2026-02-30.2026-12-31",
    "2026-13-01.2026-12-31",
    "2026-1-1.2026-12-31",
    "0000-01-01.2026-12-31",
    "2026-01-01.9999-12-31",
    "2026-01-01.2026-12-31.2027-01-01",
    "2026-01-01.",
    ".2026-12-31",
    "2026-01-01 .2026-12-31",
    "1.5",
    "",
    "abc",
    "eternity",
    "2026-02-30",
    "2026-00-01",
    "02026-01-01",
    "2026-01-01-01",
    "2026-01-01T00:00",
    "year:abc:1",
    "year:9999:1",
    "day:9999-12-31:1",
    "month:2026-13:1",
    "day:2026-02-30:1",
]
# Keys one model reads and the other doesn't.
READABLE_PERIOD_KEYS = {
    "us": [
        *COMMON_READABLE_KEYS,
        "ETERNITY",
        "2026-12-31.2026-01-01",
        "9999-12-31",
        # policyengine-core rolls a range's last day over to the next real
        # day after it (2026-03-03), so the US model applies this.
        "2026-01-01.2026-02-30",
    ],
    "uk": [*COMMON_READABLE_KEYS, "2026-1-1", "2026-1", " 2026", "2026 "],
}
UNREADABLE_PERIOD_KEYS = {
    "us": [*COMMON_UNREADABLE_KEYS, "2026-1-1", "2026-1", " 2026"],
    "uk": [
        *COMMON_UNREADABLE_KEYS,
        "2026-01-01.2026-02-30",
        "ETERNITY",
        "2026-12-31.2026-01-01",
        "9999-12-31",
    ],
}
UK_PARAMETER = "gov.hmrc.income_tax.rates.uk[0].rate"


def _key_cases(keys_by_country: dict[str, list[str]]) -> list:
    return [
        pytest.param(country_id, period_key, id=f"{country_id}-{period_key!r}")
        for country_id, period_keys in keys_by_country.items()
        for period_key in period_keys
    ]


@pytest.mark.parametrize(("country_id", "period_key"), _key_cases(READABLE_PERIOD_KEYS))
def test_a_period_key_the_countrys_model_reads_is_accepted(country_id, period_key):
    assert is_readable_period_key(period_key, country_id)


@pytest.mark.parametrize(
    ("country_id", "period_key"), _key_cases(UNREADABLE_PERIOD_KEYS)
)
def test_a_period_key_the_countrys_model_cannot_read_is_refused(
    country_id,
    period_key,
):
    assert not is_readable_period_key(period_key, country_id)


def _us_reader_reads(period_key: str) -> bool:
    """Say whether policyengine-core's Reform.from_dict applies a key.

    It applies the key to a parameter of its own, as the US model applies a
    policy to its parameters; how it reads a key doesn't depend on the
    parameter.
    """
    parameters = ParameterNode("", data={"p": {"values": {"2020-01-01": 1.0}}})
    reform = Reform.from_dict({"p": {period_key: 2.0}})
    try:
        reform.apply(SimpleNamespace(parameters=parameters))
    except ValueError:
        return False
    return True


def _uk_reader_reads(period_key: str) -> bool:
    """Say whether policyengine-uk reads a key and can write what it names.

    ``read_reform_dict`` turns each key into the first and last days a change
    covers, or a single day or month for a legacy override. The UK model then
    writes the change onto the parameter's timeline from the first day to the
    day after the last. That fails for a first or last day that doesn't exist,
    year 0, a last day of 9999-12-31 and an eternity, whose last day isn't a
    date; household calculations with the installed UK model showed each of
    these, and this helper repeats the date arithmetic.
    """
    try:
        assignments, overrides = read_reform_dict(
            {UK_PARAMETER: {period_key: 0.25}},
            defines=lambda _path: True,
        )
        covered = [(change.start, change.stop) for change in assignments] + [
            (periods.period(override.key).start, periods.period(override.key).stop)
            for override in overrides
        ]
        for first_day, last_day in covered:
            _ = first_day.date
            _ = last_day.date
            _ = last_day.offset(1, "day").date
    except (TypeError, ValueError):
        return False
    return True


@pytest.mark.parametrize(
    ("country_id", "reader_reads"),
    [("us", _us_reader_reads), ("uk", _uk_reader_reads)],
)
def test_the_period_key_check_agrees_with_the_countrys_reader(
    country_id,
    reader_reads,
):
    period_keys = READABLE_PERIOD_KEYS[country_id] + UNREADABLE_PERIOD_KEYS[country_id]
    disagreements = [
        period_key
        for period_key in period_keys
        if is_readable_period_key(period_key, country_id)
        is not reader_reads(period_key)
    ]

    assert disagreements == []


def test_an_unreadable_period_key_is_reported_with_its_path():
    period_key = "2026-02-30.2026-12-31"
    path = f"policy.{NUMBER_PARAMETER}.{period_key}"

    assert _entries({NUMBER_PARAMETER: {period_key: 3000}}) == [
        {
            "type": "policy_period",
            "name": NUMBER_PARAMETER,
            "path": path,
            "message": (
                f"Period key `{period_key}` at `{path}` must be a date range "
                "(YYYY-MM-DD.YYYY-MM-DD) or one period, such as 2026, "
                "2026-01-01 or year:2026:1, of real calendar dates before "
                "9999-12-31."
            ),
        }
    ]


def test_a_range_that_ends_before_it_starts_is_refused_for_the_uk_only():
    # The US model applies one without an error, writing the parameter's
    # values out of date order.
    period_key = "2026-12-31.2026-01-01"
    path = f"policy.{UK_PARAMETER}.{period_key}"

    assert (
        find_unreadable_policy_inputs(
            {NUMBER_PARAMETER: {period_key: 3000}}, US_METADATA, "us"
        )
        == []
    )
    assert [
        entry.to_dict()
        for entry in find_unreadable_policy_inputs(
            {UK_PARAMETER: {period_key: 0.25}}, COUNTRIES["uk"].metadata, "uk"
        )
    ] == [
        {
            "type": "policy_period",
            "name": UK_PARAMETER,
            "path": path,
            "message": (
                f"Period key `{period_key}` at `{path}` must be a date range "
                "(YYYY-MM-DD.YYYY-MM-DD) whose start is no later than its end, "
                "or one period, such as 2026, 2026-01-01 or year:2026:1, of "
                "real calendar dates before 9999-12-31."
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
    """The model converts with the same code as the check (convert_reform_value).

    So this checks the type the check reads from metadata, for parameters of
    each type, and that the check refuses every value whose conversion fails.
    """
    country = COUNTRIES[country_id]
    disagreements = []
    for value in SAMPLE_VALUES:
        policy = {parameter_name: {PERIOD: value}}
        refused = bool(
            find_unreadable_policy_inputs(policy, country.metadata, country_id)
        )
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
