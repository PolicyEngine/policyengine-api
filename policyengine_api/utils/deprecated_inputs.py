"""Detect and drop deprecated input variables before they reach the engine.

Without this, a partner who passes a removed model variable (e.g.
``medical_out_of_pocket_expenses``, deleted in policyengine-us 1.673.0)
crashes the simulation with ``VariableNotFoundError`` (HTTP 500). Dropping
the input and surfacing a structured warning gives partners a soft
landing - every other output computes normally; only outputs that
depended on the deprecated input fall back to defaults.
"""

import copy
from dataclasses import dataclass


# Registry of removed/renamed model variables that legacy partner traffic
# may still pass. The value is a one-line migration hint surfaced verbatim
# in the warning message - keep it actionable.
DEPRECATED_VARIABLES: dict[str, str] = {
    "medical_out_of_pocket_expenses": (
        "Removed in policyengine-us 1.673.0. Migrate non-premium spending "
        "to `other_medical_expenses` and premium spending to "
        "`health_insurance_premiums`."
    ),
}


@dataclass(frozen=True)
class DeprecatedVariableWarning:
    """A removed/renamed variable was supplied; dropped before the engine ran."""

    variable: str
    entity_plural: str
    entity_id: str
    hint: str

    @property
    def message(self) -> str:
        location = f"`{self.entity_plural}/{self.entity_id}`"
        if self.entity_plural == "axes":
            location = f"`axes[{self.entity_id}].name`"
        return (
            f"Input `{self.variable}` on {location} is deprecated and was "
            f"ignored for this calculation. {self.hint}"
        )


@dataclass(frozen=True)
class DeprecatedInputsResult:
    """A household copy with deprecated inputs removed plus warnings."""

    household: dict
    warnings: list[DeprecatedVariableWarning]


def drop_deprecated_inputs(
    household: dict,
) -> DeprecatedInputsResult:
    """Return a household copy with deprecated input keys stripped.

    Returns one warning per (entity, deprecated-key) occurrence. The
    caller's ``household`` is never mutated; downstream simulation
    receives the returned copy.

    Non-dict inputs are returned unchanged with no warnings; downstream
    code retains its existing bad-shape behavior.
    """
    warnings: list[DeprecatedVariableWarning] = []

    if not isinstance(household, dict):
        return DeprecatedInputsResult(household=household, warnings=warnings)

    cleaned_household = copy.deepcopy(household)

    for entity_plural, entity_group in cleaned_household.items():
        if entity_plural == "axes":
            continue
        if not isinstance(entity_group, dict):
            continue
        for entity_id, variables in entity_group.items():
            if not isinstance(variables, dict):
                continue
            for variable_name in list(variables.keys()):
                hint = DEPRECATED_VARIABLES.get(variable_name)
                if hint is None:
                    continue
                warnings.append(
                    DeprecatedVariableWarning(
                        variable=variable_name,
                        entity_plural=entity_plural,
                        entity_id=entity_id,
                        hint=hint,
                    )
                )
                del variables[variable_name]

    _drop_deprecated_axes(cleaned_household, warnings)

    return DeprecatedInputsResult(household=cleaned_household, warnings=warnings)


def _drop_deprecated_axes(
    household: dict, warnings: list[DeprecatedVariableWarning]
) -> None:
    axes = household.get("axes")
    if not isinstance(axes, list):
        return

    changed = False
    retained_entries = []

    for entry_index, entry in enumerate(axes):
        if isinstance(entry, list):
            retained_axes = []
            for axis_index, axis in enumerate(entry):
                location = f"{entry_index}][{axis_index}"
                if _is_deprecated_axis(axis, location, warnings):
                    changed = True
                    continue
                retained_axes.append(axis)
            if retained_axes:
                retained_entries.append(retained_axes)
            continue

        location = str(entry_index)
        if _is_deprecated_axis(entry, location, warnings):
            changed = True
            continue
        retained_entries.append(entry)

    if not changed:
        return
    if retained_entries:
        household["axes"] = retained_entries
    else:
        del household["axes"]


def _is_deprecated_axis(
    axis, location: str, warnings: list[DeprecatedVariableWarning]
) -> bool:
    if not isinstance(axis, dict):
        return False

    variable_name = axis.get("name")
    hint = DEPRECATED_VARIABLES.get(variable_name)
    if hint is None:
        return False

    warnings.append(
        DeprecatedVariableWarning(
            variable=variable_name,
            entity_plural="axes",
            entity_id=location,
            hint=hint,
        )
    )
    return True
