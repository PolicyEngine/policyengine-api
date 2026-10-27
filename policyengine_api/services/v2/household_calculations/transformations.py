"""Stored households and policies, in the shapes the Simulation Entrypoint takes.

A stored v2 household lists its people and each group entity as records,
each with an ``id`` and its ``values``; each person names, for every group
collection, the ``id`` of the group it belongs to. The Simulation Entrypoint's
household functions take the Public API's situation shape instead: ``people``
maps each person to their values, and each group collection, by its plural,
maps each group to its ``members`` and values. Records keep their ``id`` as
their name, so a calculated value maps back to its record.

A v2 policy stores each parameter value with its start date and an optional
end date; the household functions take the Public API's policy JSON, each
parameter's values keyed by ``YYYY-MM-DD.YYYY-MM-DD`` period ranges, where an
open end is ``2100-12-31``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from policyengine_api.services.v2.policies.types import PolicyRead

# Each country's stored group collections and their plural in the situation.
GROUP_COLLECTIONS: dict[str, dict[str, str]] = {
    "us": {
        "household": "households",
        "family": "families",
        "tax_unit": "tax_units",
        "spm_unit": "spm_units",
        "marital_unit": "marital_units",
    },
    "uk": {"household": "households", "benunit": "benunits"},
}
OPEN_END_DATE = "2100-12-31"


def household_situation(
    country_id: str, household_data: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a stored household's people and groups in the situation shape.

    The saved SPM choice is not part of the situation; ``saved_spm_choice``
    reads it.
    """
    people = household_data["people"]
    situation: dict[str, Any] = {
        "people": {person["id"]: dict(person["values"]) for person in people}
    }
    for collection, plural in GROUP_COLLECTIONS[country_id].items():
        situation[plural] = {
            group["id"]: {
                "members": [
                    person["id"]
                    for person in people
                    if person["memberships"].get(collection) == group["id"]
                ],
                **group["values"],
            }
            for group in household_data.get(collection, [])
        }
    return situation


def saved_spm_choice(household_data: Mapping[str, Any]) -> object:
    """Return the household's saved SPM selection, or None when it has none."""
    return household_data.get("spm")


def policy_parameters(policy: PolicyRead) -> dict[str, dict[str, Any]]:
    """Return the policy's values by parameter and period range."""
    parameters: dict[str, dict[str, Any]] = {}
    for value in policy.parameter_values:
        end = OPEN_END_DATE if value.end_date is None else value.end_date.date()
        period = f"{value.start_date.date().isoformat()}.{end}"
        parameters.setdefault(value.parameter_name, {})[period] = value.value
    return parameters
