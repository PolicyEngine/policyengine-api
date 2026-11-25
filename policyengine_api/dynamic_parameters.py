"""Which parameters a dynamic holds, and how a v1 policy's values are split.

A dynamic holds the model's assumptions: every parameter under
``gov.simulation.``, in every country, the US's top-level ``simulation.``
tree (C1 · 35, Q1) and the UK's ``gov.dynamic.`` (C1 · 46, Q6). These are
behavioural responses, model settings and data assumptions, which a report
applies alongside a policy. Parameters a country package adds later under
these prefixes belong to dynamics with no code change. In policyengine-uk
2.174.1, ``gov.dynamic.`` holds one parameter,
``gov.dynamic.obr_labour_supply_assumptions``, a yes/no switch.

The rule is used in these places:

- Catalog publication stores these parameters and their current-law values
  in ``dynamic_parameters`` and ``dynamic_parameter_values`` (C1 · 50), and
  every other parameter in ``parameters``; a dynamic's values are
  ``dynamic_parameter_values`` rows. The policy tree and search file leave
  them out, with the folders that hold only them
  (``is_dynamic_parameter_path``).
- ``POST /v2/policies`` refuses a policy that sets any such parameter, and
  ``POST /v2/dynamics`` refuses a dynamic that sets any other: each finds the
  IDs it lacks in the other table and names them.
- The copy of each v1 policy into v2 splits the v1 policy's values with
  ``split_legacy_policy_json``: these values become a dynamic and the rest
  the policy.
- The one-time migration splits v1 policies with the same functions.

C1 · 50's revision, which moved the rows stored before, keeps its own copy of
the prefixes, and a test keeps the two the same.

The UK renamed ``gov.simulation.labor_supply_responses`` to
``gov.simulation.labour_supply_responses`` on 2026-05-01. Its catalog has
only the new names, so a UK v1 policy saved with the old spelling is
rewritten before its parameters are looked up. In the US,
``labor_supply_responses`` is the parameter's own name and is never
rewritten.

The module imports nothing from the package, so validators, transformations
and command-line code can all import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from policyengine_api.supported_countries import SupportedCountryId

GOV_SIMULATION_PREFIX: Final = "gov.simulation."
UK_GOV_DYNAMIC_PREFIX: Final = "gov.dynamic."
DYNAMIC_PARAMETER_PREFIXES: Final[Mapping[SupportedCountryId, tuple[str, ...]]] = {
    "uk": (GOV_SIMULATION_PREFIX, UK_GOV_DYNAMIC_PREFIX),
    "us": (GOV_SIMULATION_PREFIX, "simulation."),
}
UK_OLD_LABOUR_SUPPLY_PREFIX: Final = "gov.simulation.labor_supply_responses."
UK_LABOUR_SUPPLY_PREFIX: Final = "gov.simulation.labour_supply_responses."


class ConflictingParameterSpellingsError(ValueError):
    """A v1 policy sets one parameter under both UK spellings, and they disagree.

    Both spellings' values are period objects, merged into one; the policy is
    refused when either is not a period object or both give one period
    different values.
    """


@dataclass(frozen=True)
class LegacyPolicySplit:
    """A v1 policy's ``{path: {period: value}}`` object, split in two.

    ``dynamic_values`` holds the parameters a dynamic holds, and
    ``policy_values`` the rest, each keyed by the parameter's current name.
    Either may be empty.
    """

    policy_values: dict[str, object]
    dynamic_values: dict[str, object]


def is_dynamic_parameter(country_id: SupportedCountryId, parameter_name: str) -> bool:
    """Return whether the country's parameter belongs in a dynamic, not a policy."""
    return parameter_name.startswith(DYNAMIC_PARAMETER_PREFIXES[country_id])


def is_dynamic_parameter_path(country_id: SupportedCountryId, path: str) -> bool:
    """Return whether a node or parameter path holds only model assumptions.

    That is a dynamic folder itself (``gov.simulation``, US ``simulation``, UK
    ``gov.dynamic``) or anything below one, a bracket included: the path
    followed by ``.`` starts with one of the country's prefixes. ``gov`` holds
    policy parameters too, so it is not one. For a parameter's name this is
    ``is_dynamic_parameter``. The policy tree and search file leave these
    paths out, and C1 · 50's revision deletes their stored tree rows by the
    same rule.
    """
    return f"{path}.".startswith(DYNAMIC_PARAMETER_PREFIXES[country_id])


def canonical_parameter_name(
    country_id: SupportedCountryId, parameter_name: str
) -> str:
    """Return the parameter's current name: the UK's old spelling rewritten."""
    if country_id == "uk" and parameter_name.startswith(UK_OLD_LABOUR_SUPPLY_PREFIX):
        return UK_LABOUR_SUPPLY_PREFIX + parameter_name.removeprefix(
            UK_OLD_LABOUR_SUPPLY_PREFIX
        )
    return parameter_name


def _merged_period_values(
    parameter_name: str, earlier: object, later: object
) -> dict[object, object]:
    """Merge two spellings' period objects; raise when they disagree."""
    if type(earlier) is not dict or type(later) is not dict:
        msg = f"parameter {parameter_name!r} is set under both spellings"
        raise ConflictingParameterSpellingsError(msg)
    for period, value in later.items():
        if period in earlier and earlier[period] != value:
            msg = (
                f"parameter {parameter_name!r} is set under both spellings "
                f"with different values for {period!r}"
            )
            raise ConflictingParameterSpellingsError(msg)
    return {**earlier, **later}


def split_legacy_policy_json(
    country_id: SupportedCountryId, policy_json: Mapping[str, object]
) -> LegacyPolicySplit:
    """Split a v1 policy's values into the policy's and the dynamic's.

    Each parameter path is first given its current name
    (``canonical_parameter_name``). A UK policy that sets one parameter under
    both spellings has their period objects merged; raise
    ConflictingParameterSpellingsError when they can't be. The values
    themselves are left as they are, for the translation to check.
    """
    renamed: dict[str, object] = {}
    for parameter_name, period_values in policy_json.items():
        current_name = canonical_parameter_name(country_id, parameter_name)
        if current_name in renamed:
            renamed[current_name] = _merged_period_values(
                current_name, renamed[current_name], period_values
            )
        else:
            renamed[current_name] = period_values
    return LegacyPolicySplit(
        policy_values={
            name: values
            for name, values in renamed.items()
            if not is_dynamic_parameter(country_id, name)
        },
        dynamic_values={
            name: values
            for name, values in renamed.items()
            if is_dynamic_parameter(country_id, name)
        },
    )
