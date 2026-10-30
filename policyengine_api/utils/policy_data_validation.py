"""Check a policy's period keys and values against what simulations can read.

A policy's ``data`` maps each parameter path to an object of period keys and
values. The simulation service reads a period key as one date or as a start and
end date joined by ``.``, parsed as ``%Y-%m-%d``, and refuses an end before the
start (policyengine-sim-api ``request_policy.py``). policyengine-core, which
runs household calculations, reads only zero-padded ``YYYY-MM-DD`` dates. A
period key passes when both read it: one zero-padded date, or two joined by
``.``, of real calendar dates with the start no later than the end.

policyengine-core stores a parameter value only when it is a number, a boolean,
None or a list, and refuses any other type. The Public API writes an infinite
value as the string ``"Infinity"`` or ``"-Infinity"``, so those strings pass
too. A number must be finite, because standard JSON has no NaN or infinity.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date

# Longer received values are described by their type, not quoted, in messages.
_MAX_QUOTED_VALUE_LENGTH = 40
# A period key is one date, or a start and an end date joined by ".".
_MAX_DATES_IN_PERIOD_KEY = 2
_ZERO_PADDED_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INFINITE_VALUE_STRINGS = frozenset({"Infinity", "-Infinity"})

PERIOD_KEY_REQUIREMENT = (
    "a date (YYYY-MM-DD) or an inclusive date range (YYYY-MM-DD.YYYY-MM-DD) of "
    "real calendar dates whose start is no later than its end"
)
VALUE_REQUIREMENT = (
    'a finite number, a boolean, null, a list, or the string "Infinity" or "-Infinity"'
)
PERIOD_OBJECT_REQUIREMENT = (
    'an object of period keys and values, such as {"2026-01-01.2026-12-31": 1}'
)


@dataclass(frozen=True)
class InvalidPolicyEntry:
    """One part of a policy's data that simulations cannot read.

    ``input_type`` is ``policy_period`` for a period key, or for a parameter
    whose value is not an object of period keys, and ``policy_value`` for a
    value. ``path`` locates the entry: ``data.<parameter>`` or
    ``data.<parameter>.<period key>``. ``received`` describes a refused value
    or a parameter's non-object value, and is None for a refused period key.
    """

    input_type: str
    parameter_path: str
    path: str
    period_key: str | None = None
    received: str | None = None

    @property
    def message(self) -> str:
        """A one-sentence, user-facing description of the problem and where it is."""
        if self.input_type == "policy_value":
            return (
                f"Value at `{self.path}` must be {VALUE_REQUIREMENT}, "
                f"but it is {self.received}."
            )
        if self.period_key is None:
            return (
                f"`{self.path}` must be {PERIOD_OBJECT_REQUIREMENT}, "
                f"but it is {self.received}."
            )
        return (
            f"Period key `{self.period_key}` at `{self.path}` must be "
            f"{PERIOD_KEY_REQUIREMENT}."
        )

    def to_dict(self) -> dict:
        """Return the JSON error entry, with the keys of an unrecognized input's."""
        return {
            "type": self.input_type,
            "name": self.parameter_path,
            "path": self.path,
            "message": self.message,
        }


def find_invalid_periods_and_values(
    policy_data: dict,
) -> tuple[InvalidPolicyEntry, ...]:
    """Return every period key and value in a policy that simulations cannot read.

    Entries are ordered by parameter path, then in the order the policy gives
    each parameter's periods; a period key that is refused comes before its
    value. A parameter whose value is not an object gives one entry.
    """
    invalid_entries: list[InvalidPolicyEntry] = []
    for parameter_path in sorted(policy_data):
        invalid_entries.extend(
            _invalid_entries_for_parameter(parameter_path, policy_data[parameter_path])
        )
    return tuple(invalid_entries)


def _invalid_entries_for_parameter(
    parameter_path: str,
    period_values: object,
) -> list[InvalidPolicyEntry]:
    parameter_data_path = f"data.{parameter_path}"
    if not isinstance(period_values, dict):
        return [
            InvalidPolicyEntry(
                input_type="policy_period",
                parameter_path=parameter_path,
                path=parameter_data_path,
                received=_describe_value(period_values),
            )
        ]
    invalid_entries: list[InvalidPolicyEntry] = []
    for period_key, value in period_values.items():
        entry_path = f"{parameter_data_path}.{period_key}"
        if not is_readable_period_key(period_key):
            invalid_entries.append(
                InvalidPolicyEntry(
                    input_type="policy_period",
                    parameter_path=parameter_path,
                    path=entry_path,
                    period_key=period_key,
                )
            )
        if not is_readable_value(value):
            invalid_entries.append(
                InvalidPolicyEntry(
                    input_type="policy_value",
                    parameter_path=parameter_path,
                    path=entry_path,
                    period_key=period_key,
                    received=_describe_value(value),
                )
            )
    return invalid_entries


def is_readable_period_key(period_key: str) -> bool:
    """Say whether a period key is one date, or a date range, both read.

    Each date is zero-padded ``YYYY-MM-DD`` and exists in the calendar, and a
    range's end is no earlier than its start.
    """
    date_texts = period_key.split(".")
    if len(date_texts) > _MAX_DATES_IN_PERIOD_KEY:
        return False
    if not all(_ZERO_PADDED_DATE.fullmatch(date_text) for date_text in date_texts):
        return False
    try:
        dates = [date.fromisoformat(date_text) for date_text in date_texts]
    except ValueError:
        return False
    return dates[0] <= dates[-1]


def is_readable_value(value: object) -> bool:
    """Say whether policyengine-core stores the value, or it is a written infinity."""
    if value is None or isinstance(value, (bool, int, list)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str) and value in _INFINITE_VALUE_STRINGS


def _describe_value(value: object) -> str:
    """Describe a received JSON value: as JSON writes it, or by type if long."""
    written_value = json.dumps(value)
    if len(written_value) <= _MAX_QUOTED_VALUE_LENGTH:
        return written_value
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, str):
        return "a string"
    return "a number"
