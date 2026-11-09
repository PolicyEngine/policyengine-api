"""Find the stored policies of an economic impact that simulations can't read.

Policies saved before the Public API checked new policies' period keys and
values (``PolicyService._check_policy_data``) may hold entries no simulation
can read: US policy 29093 stores two amounts as text. Every economy job for
such a policy fails while the model reads its parameters (issue #4244). So the
economy service checks an impact's stored policies with the checks new
policies get (``policyengine_api.utils.policy_data_validation``) before it
starts a job or replays a stored failure, and the routes answer 422 instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from policyengine_api.utils.policy_data_validation import (
    InvalidPolicyEntry,
    find_invalid_periods_and_values,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


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
        invalid_entries = find_invalid_periods_and_values(policy_data)
        if invalid_entries:
            unreadable.append(UnreadablePolicy(policy_id, invalid_entries))
    return UnreadablePolicies(tuple(unreadable)) if unreadable else None
