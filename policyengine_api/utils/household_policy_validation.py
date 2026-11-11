"""Check a household calculation's policy against what the calculation can read.

A household calculation reads its ``policy`` as an object of parameter paths,
each set to an object of period keys and values:

- ``PolicyEngineCountry._normalize_reform_values`` converts each value to the
  type of the parameter's earliest value, reading an int as a float, after
  trying ``float()`` on it. ``float()`` and ``list()`` refuse some values; a
  boolean parameter takes anything, since ``bool()`` converts any value.
- The country model then reads each period key: the UK model with its own
  reader (``policyengine_uk.utils.dated_reforms``), the US model with
  policyengine-core's ``Reform.from_dict``. Both read a key with a ``.`` as
  a range of two dates, each one policyengine-core's ``instant()`` reads (a
  zero-padded ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``), and a key with a
  ``:``, such as ``year:2026:5``, with policyengine-core's ``period()``. The
  UK model refuses a range that ends before it starts; the US model applies
  it, writing the parameter's values out of date order. A key with neither
  is one date: the US model reads it with ``instant()``, or reads
  ``ETERNITY``; the UK model reads a year from 1901 to 2199, spaces around
  it allowed, as that fiscal year, and anything else with ``period()``, which
  also reads unpadded months and days. Both then write the change to the
  parameter from its first day to the day after its last, so the first day
  must be a real calendar date and the last day before 9999-12-31. The UK
  model needs a real last day too; policyengine-core rolls one that doesn't
  exist, such as 2026-02-30, over to the real day after it.

A policy that fails there fails after the model's tax-benefit system has been
copied, which takes seconds. This module finds those problems beforehand, from
the country metadata and the reader of the country being calculated, so the
request can be refused with a 400. It refuses what the conversion or that
reader would fail on, and accepts what they read.

An empty or null ``policy`` means no policy, as the calculation reads it.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from policyengine_core import periods

from policyengine_api.utils.policy_data_validation import (
    PERIOD_OBJECT_REQUIREMENT,
    describe_value,
)

# Metadata writes an infinite parameter value as this text.
_WRITTEN_INFINITIES = frozenset({"Infinity", "-Infinity"})
# The country whose model reads keys with policyengine-uk's reader; every other
# model reads them with policyengine-core's Reform.from_dict.
UK_COUNTRY_ID = "uk"
# The one eternity key policyengine-core's reader reads; the UK model reads none.
_ETERNITY_KEY = "ETERNITY"
_ETERNITY_UNIT = "eternity"
# policyengine-uk reads a bare year after 1900 and before 2200 as a fiscal year
# (dated_reforms.bare_year).
_UK_BARE_YEARS = range(1901, 2200)
_ERRORS_READING_A_PERIOD = (TypeError, ValueError, OverflowError)

POLICY_REQUIREMENT = (
    "an object of parameter paths, each set to an object of period keys and values"
)
_PERIOD_REQUIREMENT = (
    "one period, such as 2026, 2026-01-01 or year:2026:1, of real calendar "
    "dates before 9999-12-31"
)
NUMBER_REQUIREMENT = 'a number, or text that reads as one such as "Infinity"'
LIST_REQUIREMENT = "a list"


@dataclass(frozen=True)
class UnreadablePolicyInput:
    """One part of a calculation's policy that the calculation can't read.

    ``input_type`` is ``policy`` for a policy that isn't an object,
    ``policy_period`` for a parameter whose value isn't an object of period
    keys, or for a period key, and ``policy_value`` for a value. ``path`` is
    ``policy``, ``policy.<parameter>`` or ``policy.<parameter>.<period key>``.
    ``received`` describes a refused value, and is None for a period key.
    """

    input_type: str
    name: str
    path: str
    requirement: str
    received: str | None = None
    period_key: str | None = None

    @property
    def message(self) -> str:
        """A one-sentence, user-facing description of the problem and where it is."""
        if self.period_key is not None and self.input_type == "policy_period":
            return (
                f"Period key `{self.period_key}` at `{self.path}` must be "
                f"{self.requirement}."
            )
        if self.input_type == "policy_value":
            return (
                f"Value at `{self.path}` must be {self.requirement}, "
                f"but it is {self.received}."
            )
        return f"`{self.path}` must be {self.requirement}, but it is {self.received}."

    def to_dict(self) -> dict:
        """Return the JSON error entry, with the keys of an unrecognized input's."""
        return {
            "type": self.input_type,
            "name": self.name,
            "path": self.path,
            "message": self.message,
        }


def find_unreadable_policy_inputs(
    policy: object,
    metadata: dict,
    country_id: str,
) -> list[UnreadablePolicyInput]:
    """Return every part of a calculation's policy that the calculation can't read.

    ``metadata`` and ``country_id`` are the country being calculated. Entries
    follow the policy's order, and a period key that is refused comes before
    its value. A value is checked only for a parameter whose earliest value
    the metadata records; a name the model lacks is reported by
    ``find_unrecognized_policy_inputs``.
    """
    if not policy:
        return []
    if not isinstance(policy, dict):
        return [
            UnreadablePolicyInput(
                input_type="policy",
                name="policy",
                path="policy",
                requirement=POLICY_REQUIREMENT,
                received=describe_value(policy),
            )
        ]
    parameters = metadata.get("parameters", {})
    unreadable_inputs: list[UnreadablePolicyInput] = []
    for parameter_name, period_values in policy.items():
        unreadable_inputs.extend(
            _unreadable_parameter_inputs(
                parameter_name,
                period_values,
                reform_value_type(parameters.get(parameter_name)),
                country_id,
            )
        )
    return unreadable_inputs


def _unreadable_parameter_inputs(
    parameter_name: str,
    period_values: object,
    value_type: type | None,
    country_id: str,
) -> list[UnreadablePolicyInput]:
    parameter_path = f"policy.{parameter_name}"
    if not isinstance(period_values, dict):
        return [
            UnreadablePolicyInput(
                input_type="policy_period",
                name=parameter_name,
                path=parameter_path,
                requirement=PERIOD_OBJECT_REQUIREMENT,
                received=describe_value(period_values),
            )
        ]
    unreadable_inputs: list[UnreadablePolicyInput] = []
    for period_key, value in period_values.items():
        # Both models' readers read a key that isn't text as its text.
        period_key_text = str(period_key)
        entry_path = f"{parameter_path}.{period_key_text}"
        if not is_readable_period_key(period_key_text, country_id):
            unreadable_inputs.append(
                UnreadablePolicyInput(
                    input_type="policy_period",
                    name=parameter_name,
                    path=entry_path,
                    requirement=period_key_requirement(country_id),
                    period_key=period_key_text,
                )
            )
        if value_type is not None and not _converts(value, value_type):
            unreadable_inputs.append(
                UnreadablePolicyInput(
                    input_type="policy_value",
                    name=parameter_name,
                    path=entry_path,
                    requirement=_value_requirement(value_type),
                    received=describe_value(value),
                    period_key=period_key_text,
                )
            )
    return unreadable_inputs


def period_key_requirement(country_id: str) -> str:
    """Say which period keys the model of ``country_id`` reads."""
    if country_id == UK_COUNTRY_ID:
        return (
            "a date range (YYYY-MM-DD.YYYY-MM-DD) whose start is no later than "
            f"its end, or {_PERIOD_REQUIREMENT}"
        )
    return f"a date range (YYYY-MM-DD.YYYY-MM-DD) or {_PERIOD_REQUIREMENT}"


def is_readable_period_key(period_key: str, country_id: str) -> bool:
    """Say whether the model of ``country_id`` reads a period key and can apply it."""
    uk = country_id == UK_COUNTRY_ID
    if "." in period_key:
        return _is_readable_range(period_key, read_as_by_uk_model=uk)
    if ":" in period_key:
        return _is_readable_period(period_key)
    if uk:
        return _is_uk_bare_year(period_key) or _is_readable_period(period_key)
    return period_key == _ETERNITY_KEY or _is_readable_instant(period_key)


def _is_readable_range(period_key: str, *, read_as_by_uk_model: bool) -> bool:
    """Say whether a model applies a ``start.end`` key.

    Both models need a real first day, and a last day whose next day is real,
    so it is before 9999-12-31. policyengine-core rolls a last day that
    doesn't exist, such as 2026-02-30, over to the real day after it, so the
    US model applies such a key; the UK model needs a real last day no
    earlier than the first.
    """
    start_text, _, end_text = period_key.partition(".")
    if "." in end_text:
        return False
    try:
        start = periods.instant(start_text)
        end = periods.instant(end_text)
        _ = start.date
        _ = end.offset(1, "day").date
        if read_as_by_uk_model:
            _ = end.date
    except _ERRORS_READING_A_PERIOD:
        return False
    return start <= end or not read_as_by_uk_model


def _is_readable_period(period_key: str) -> bool:
    """Say whether policyengine-core reads a key as a period of real days.

    The period's last day must be before 9999-12-31, and it can't be an
    eternity, which has no last day.
    """
    try:
        period = periods.period(period_key)
        if period.unit == _ETERNITY_UNIT:
            return False
        _ = period.start.date
        _ = period.stop.offset(1, "day").date
    except _ERRORS_READING_A_PERIOD:
        return False
    return True


def _is_readable_instant(period_key: str) -> bool:
    """Say whether policyengine-core's ``instant()`` reads a key as a real day."""
    try:
        _ = periods.instant(period_key).date
    except _ERRORS_READING_A_PERIOD:
        return False
    return True


def _is_uk_bare_year(period_key: str) -> bool:
    """Say whether policyengine-uk reads a key as a bare year.

    ``isdigit()`` is true for characters such as ``²`` that ``int()`` refuses.
    policyengine-uk fails on those, so the key is refused.
    """
    year_text = period_key.strip()
    if not year_text.isdigit():
        return False
    try:
        return int(year_text) in _UK_BARE_YEARS
    except ValueError:
        return False


def reform_value_type(parameter_metadata: object) -> type | None:
    """Return the type the calculation converts a parameter's values to, if known.

    It is the type of the parameter's earliest value, with an int read as a
    float. Metadata lists a parameter's values latest first, so the earliest
    is the last; it writes an infinity as text, and a value it can't write,
    such as a date, as null. A null earliest value gives None, as does a
    parameter without values: the calculation decides what those take.
    """
    if not isinstance(parameter_metadata, dict):
        return None
    values = parameter_metadata.get("values")
    if not isinstance(values, dict) or not values:
        return None
    earliest_value = next(reversed(values.values()))
    if earliest_value is None:
        return None
    if isinstance(earliest_value, str) and earliest_value in _WRITTEN_INFINITIES:
        return float
    return conversion_type(earliest_value)


def conversion_type(earliest_value: object) -> type:
    """Return the type a parameter's values convert to, from its earliest value.

    An int is read as a float, so a parameter first set to 0 takes 0.5.
    """
    value_type = type(earliest_value)
    return float if value_type is int else value_type


def convert_reform_value(value: object, value_type: type) -> object:
    """Convert a policy value to a parameter's type, as the calculation does.

    Text that reads as a number, such as ``"2500"`` or ``"Infinity"``, is read
    as that number first. Raises TypeError, ValueError or OverflowError when
    the type can't take the value.
    """
    numeric_value = value
    with contextlib.suppress(TypeError, ValueError, OverflowError):
        numeric_value = float(value)
    return value_type(numeric_value)


def _value_requirement(value_type: type) -> str:
    """Say what a parameter whose values convert to ``value_type`` takes."""
    if issubclass(value_type, float):
        return NUMBER_REQUIREMENT
    if issubclass(value_type, list):
        return LIST_REQUIREMENT
    return f"a value of type {value_type.__name__}"


def _converts(value: object, value_type: type) -> bool:
    try:
        convert_reform_value(value, value_type)
    except (TypeError, ValueError, OverflowError):
        return False
    return True
