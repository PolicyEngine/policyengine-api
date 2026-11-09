"""Find the stored policies of an economic impact that simulations can't read.

Policies saved before the Public API checked new policies' period keys and
values (``PolicyService._check_policy_data``) may hold entries no simulation
can read: US policy 29093 stores two amounts as text. Every economy job for
such a policy fails while the model reads its parameters (issue #4244). So the
economy service checks an impact's stored policies before it starts a job or
replays a stored failure, and the routes answer 422 instead.

The check uses the value check new policies get (``is_readable_value`` in
``policyengine_api.utils.policy_data_validation``), but refuses only what
economy simulations refuse. The checks for new policies also cover household
calculations, which read only zero-padded dates and only objects of periods.
Economy simulations read a policy through the simulation service and .py: the
simulation service parses each period key with ``strptime`` and
``%Y-%m-%d``, which also reads unpadded months and days, and refuses a range
whose end is before its start (policyengine-sim-api ``request_policy.py``),
and .py applies a value given without periods from 1 January of the
simulated year (``compile_reform``). A stored policy written either way runs
today, so it isn't refused.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from policyengine_api.utils.policy_data_validation import (
    InvalidPolicyEntry,
    describe_value,
    is_readable_value,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

# A period key is one date, or a start and an end date joined by ".".
_MAX_DATES_IN_PERIOD_KEY = 2


@dataclass(frozen=True)
class UnreadablePolicy:
    """A stored policy and the period keys and values in it simulations can't read."""

    policy_id: int
    invalid_entries: tuple[InvalidPolicyEntry, ...]

    @property
    def message(self) -> str:
        """Name the policy and every refused entry, with its parameter and period."""
        return (
            f"Policy #{self.policy_id} holds period keys or values that simulations "
            "can't read, so no economic impact can be calculated for it: "
            + " ".join(entry.message for entry in self.invalid_entries)
        )


@dataclass(frozen=True)
class UnreadablePolicies:
    """The stored policies of one economic impact that simulations can't read."""

    policies: tuple[UnreadablePolicy, ...]

    @property
    def message(self) -> str:
        """The 422 response's message: each policy's message, in order."""
        return " ".join(policy.message for policy in self.policies)

    @property
    def error_entries(self) -> list[dict]:
        """The 422 response's ``errors``: each refused entry, with its policy ID."""
        return [
            {**entry.to_dict(), "policy_id": policy.policy_id}
            for policy in self.policies
            for entry in policy.invalid_entries
        ]

    @property
    def policy_ids(self) -> tuple[int, ...]:
        """The IDs of the policies simulations can't read, in order."""
        return tuple(policy.policy_id for policy in self.policies)

    @property
    def invalid_entry_count(self) -> int:
        """How many period keys and values the policies hold that are refused."""
        return sum(len(policy.invalid_entries) for policy in self.policies)


def simulation_service_reads_period_key(period_key: str) -> bool:
    """Say whether the simulation service reads a period key.

    It reads one date or two joined by ``.``, each parsed with ``strptime`` and
    ``%Y-%m-%d`` (which also takes unpadded months and days), with the end no
    earlier than the start.
    """
    date_texts = period_key.split(".")
    if len(date_texts) > _MAX_DATES_IN_PERIOD_KEY:
        return False
    try:
        dates = [time.strptime(date_text, "%Y-%m-%d")[:3] for date_text in date_texts]
    except ValueError:
        return False
    return dates[0] <= dates[-1]


def find_entries_economy_simulations_refuse(
    policy_data: dict,
) -> tuple[InvalidPolicyEntry, ...]:
    """Return the period keys and values in a stored policy economy jobs refuse.

    Entries are ordered by parameter path, then in the order the policy gives
    each parameter's periods; a refused period key comes before its value. A
    parameter given one value without periods is checked as that value.
    """
    invalid_entries: list[InvalidPolicyEntry] = []
    for parameter_path in sorted(policy_data):
        period_values = policy_data[parameter_path]
        parameter_data_path = f"data.{parameter_path}"
        if not isinstance(period_values, dict):
            if not is_readable_value(period_values):
                invalid_entries.append(
                    InvalidPolicyEntry(
                        input_type="policy_value",
                        parameter_path=parameter_path,
                        path=parameter_data_path,
                        received=describe_value(period_values),
                    )
                )
            continue
        for period_key, value in period_values.items():
            entry_path = f"{parameter_data_path}.{period_key}"
            if not simulation_service_reads_period_key(period_key):
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
                        received=describe_value(value),
                    )
                )
    return tuple(invalid_entries)


def find_unreadable_policies(
    stored_policies: Iterable[tuple[int, dict]],
) -> UnreadablePolicies | None:
    """Return the policies whose data simulations can't read, or None if all pass.

    ``stored_policies`` gives each policy's ID and stored JSON object, the
    reform's first; a policy given twice, as when an impact compares a policy
    with itself, is checked once.
    """
    unreadable: list[UnreadablePolicy] = []
    checked_ids: set[int] = set()
    for policy_id, policy_data in stored_policies:
        if policy_id in checked_ids:
            continue
        checked_ids.add(policy_id)
        invalid_entries = find_entries_economy_simulations_refuse(policy_data)
        if invalid_entries:
            unreadable.append(UnreadablePolicy(policy_id, invalid_entries))
    return UnreadablePolicies(tuple(unreadable)) if unreadable else None
