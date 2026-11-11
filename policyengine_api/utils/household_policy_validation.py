"""Check a household calculation's policy against what the calculation can read.

A household calculation reads its ``policy`` as an object of parameter paths,
each set to an object of period keys and values:

- ``PolicyEngineCountry._normalize_reform_values`` converts each value to the
  type of the parameter's earliest value, reading an int as a float, after
  trying ``float()`` on it. ``float()`` and ``list()`` refuse some values; a
  boolean parameter takes anything, since ``bool()`` converts any value.
- The country model then reads each period key: the US model with
  policyengine-core's ``Reform.from_dict``, the UK model with its own reader
  (``policyengine_uk.utils.dated_reforms``). Both read a key with a ``.`` as
  a range of two dates, each a zero-padded ``YYYY``, ``YYYY-MM`` or
  ``YYYY-MM-DD`` that policyengine-core's ``instant()`` reads. Both read a key
  with a ``:``, such as ``year:2026:5``, with policyengine-core's
  ``period()``. A key with neither is one date: the US model reads it with
  ``instant()`` and the UK model with ``period()``, which also reads unpadded
  months and days. Only the US model reads ``ETERNITY``.

A policy that fails there fails after the model's tax-benefit system has been
copied, which takes seconds. This module finds those problems beforehand, from
the country metadata, so the request can be refused with a 400. It refuses
what the conversion, or both models' readers, would fail on, and a range that
ends before it starts, which the UK model refuses and the US model writes out
of date order. It accepts anything one model reads, so a key only one model
reads still fails in the other.

An empty or null ``policy`` means no policy, as the calculation reads it.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import date

from policyengine_core import periods

from policyengine_api.utils.policy_data_validation import (
    PERIOD_OBJECT_REQUIREMENT,
    describe_value,
)

# Metadata writes an infinite parameter value as this text.
_WRITTEN_INFINITIES = frozenset({"Infinity", "-Infinity"})
# One end of a range: a zero-padded year, month or day, as policyengine-core's
# instant() reads it.
_RANGE_END = re.compile(r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?")
# The one eternity key the US model reads; the UK model reads none.
_ETERNITY_KEY = "ETERNITY"
_ETERNITY_UNIT = "eternity"

POLICY_REQUIREMENT = (
    "an object of parameter paths, each set to an object of period keys and values"
)
PERIOD_KEY_REQUIREMENT = (
    "a range of two dates (YYYY-MM-DD.YYYY-MM-DD) whose start is no later than "
    "its end, or one period such as 2026, 2026-01-01 or year:2026:1"
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
) -> list[UnreadablePolicyInput]:
    """Return every part of a calculation's policy that the calculation can't read.

    Entries follow the policy's order, and a period key that is refused comes
    before its value. A value is checked only for a parameter whose earliest
    value the metadata records; a name the model lacks is reported by
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
            )
        )
    return unreadable_inputs


def _unreadable_parameter_inputs(
    parameter_name: str,
    period_values: object,
    value_type: type | None,
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
        if not is_readable_period_key(period_key_text):
            unreadable_inputs.append(
                UnreadablePolicyInput(
                    input_type="policy_period",
                    name=parameter_name,
                    path=entry_path,
                    requirement=PERIOD_KEY_REQUIREMENT,
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


def is_readable_period_key(period_key: str) -> bool:
    """Say whether the US or the UK model reads a period key.

    A range's ends are real calendar dates, and its end is no earlier than its
    start. Any other key is ``ETERNITY`` or a period policyengine-core parses,
    other than an eternity.
    """
    if "." in period_key:
        start_text, _, end_text = period_key.partition(".")
        start = _range_end_date(start_text)
        end = _range_end_date(end_text)
        return start is not None and end is not None and start <= end
    if period_key == _ETERNITY_KEY:
        return True
    try:
        parsed_period = periods.period(period_key)
    except (ValueError, OverflowError):
        return False
    return parsed_period.unit != _ETERNITY_UNIT


def _range_end_date(text: str) -> date | None:
    """Return the first day a range end names, or None if it names none."""
    match = _RANGE_END.fullmatch(text)
    if match is None:
        return None
    year, month, day = (int(part) if part else 1 for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


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
