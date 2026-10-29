"""Check household axes against what policyengine-core can expand.

policyengine-core reads ``axes`` as a list of axis groups. The axes in one group
vary together, and two or more groups form a grid. Each axis is an object naming
a variable, with ``min``, ``max``, ``count`` and optional ``period`` and ``index``
fields. ``SimulationBuilder.expand_axes`` raises an arbitrary exception for any
other shape, which a calculation route would report as a 500. These checks read
the same fields under the same conditions, so every shape policyengine-core
expands passes and every shape it cannot expand is reported as an input error.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from policyengine_core import periods

# Marks an axis field that the request leaves out.
_MISSING = object()
# Longer strings are described by their type, not quoted, in error messages.
_MAX_QUOTED_STRING_LENGTH = 40


@dataclass(frozen=True)
class InvalidAxisInput:
    """One part of a household's axes that policyengine-core cannot expand.

    ``path`` locates the axis, the axis group or the ``axes`` value itself.
    ``field`` names the axis field at fault, or is None when the value at
    ``path`` has the wrong structure. ``requirement`` says what the value must
    be, and ``received`` describes what the request sent.
    """

    path: str
    requirement: str
    received: str
    field: str | None = None
    variable_name: str | None = None

    @property
    def message(self) -> str:
        """A one-sentence, user-facing description of the problem and where it is."""
        if self.field is None:
            return (
                f"`{self.path}` must be {self.requirement}, but it is {self.received}."
            )
        variable = "" if self.variable_name is None else f" (`{self.variable_name}`)"
        return (
            f"Household axis `{self.path}`{variable} needs `{self.field}` to be "
            f"{self.requirement}, but it is {self.received}."
        )

    def to_dict(self) -> dict:
        """Return the JSON error entry, with the keys of an unrecognized input's."""
        return {
            "type": "household_axis",
            "name": self.field or "axes",
            "path": self.path if self.field is None else f"{self.path}.{self.field}",
            "message": self.message,
        }


def find_invalid_axes(axes: object) -> list[InvalidAxisInput]:
    """Report each part of a household's ``axes`` that policyengine-core cannot expand.

    policyengine-core ignores ``axes`` that are missing, null or empty. Otherwise
    it reads the count of each axis group's first axis only, and the name, min
    and max of every axis, along with its period and index when they are given.
    In a grid, an axis group of one point sets each of its axes to its min, so
    max is not read there. Fields policyengine-core never reads are not checked.
    """
    if not axes:
        return []
    if not isinstance(axes, list):
        return [
            InvalidAxisInput(
                path="household.axes",
                requirement="a list of axis groups",
                received=_describe(axes),
            )
        ]

    is_grid = len(axes) > 1
    errors: list[InvalidAxisInput] = []
    for group_index, axis_group in enumerate(axes):
        group_path = f"household.axes[{group_index}]"
        if not isinstance(axis_group, list) or not axis_group:
            errors.append(
                InvalidAxisInput(
                    path=group_path,
                    requirement="a non-empty list of axes",
                    received=_describe(axis_group),
                )
            )
            continue
        errors.extend(_find_invalid_axis_group(axis_group, group_path, is_grid=is_grid))
    return errors


def _find_invalid_axis_group(
    axis_group: list,
    group_path: str,
    *,
    is_grid: bool,
) -> list[InvalidAxisInput]:
    first_axis = axis_group[0]
    group_count = (
        first_axis.get("count", _MISSING) if isinstance(first_axis, dict) else _MISSING
    )
    reads_max = not (is_grid and group_count == 1)

    errors: list[InvalidAxisInput] = []
    for axis_index, axis in enumerate(axis_group):
        axis_path = f"{group_path}[{axis_index}]"
        if not isinstance(axis, dict):
            errors.append(
                InvalidAxisInput(
                    path=axis_path,
                    requirement="an axis object",
                    received=_describe(axis),
                )
            )
            continue
        errors.extend(
            _find_invalid_axis_fields(
                axis,
                axis_path,
                reads_count=axis_index == 0,
                reads_max=reads_max,
                is_grid=is_grid,
            )
        )
    return errors


def _find_invalid_axis_fields(
    axis: dict,
    axis_path: str,
    *,
    reads_count: bool,
    reads_max: bool,
    is_grid: bool,
) -> list[InvalidAxisInput]:
    """Check the fields policyengine-core reads from one axis.

    ``reads_count`` is true for a group's first axis, and ``reads_max`` is false
    for an axis group of one point in a grid.
    """
    name = axis.get("name", _MISSING)
    variable_name = name if isinstance(name, str) else None
    # Each entry: a field, whether its value is usable, and what it must be.
    checked_fields: list[tuple[str, bool, str]] = [
        ("name", variable_name is not None, "a variable name"),
    ]
    if reads_count:
        count = axis.get("count", _MISSING)
        checked_fields.append(
            (
                "count",
                isinstance(count, int) and count >= 1,
                "an integer of at least 1, written without a decimal point",
            )
        )
    measured_fields = ("min", "max") if reads_max else ("min",)
    checked_fields.extend(
        (field, _is_finite_number(axis.get(field, _MISSING)), "a finite number")
        for field in measured_fields
    )
    if "period" in axis:
        checked_fields.append(
            (
                "period",
                _is_period(axis["period"], is_grid=is_grid),
                "a period such as 2026 or 2026-01",
            )
        )
    if "index" in axis:
        index = axis["index"]
        checked_fields.append(
            (
                "index",
                index is None or isinstance(index, int),
                "an integer written without a decimal point, or null",
            )
        )

    return [
        InvalidAxisInput(
            path=axis_path,
            requirement=requirement,
            received=_describe(axis.get(field, _MISSING)),
            field=field,
            variable_name=variable_name,
        )
        for field, is_usable, requirement in checked_fields
        if not is_usable
    ]


def _is_finite_number(value: object) -> bool:
    """Whether numpy can space values to or from ``value``.

    JSON booleans count, because policyengine-core reads them as 0 and 1.
    """
    return isinstance(value, int | float) and math.isfinite(value)


def _is_period(value: object, *, is_grid: bool) -> bool:
    """Whether policyengine-core can read ``value`` as an axis period.

    In a grid, policyengine-core uses the default period in place of any falsy
    value, null included. A single axis group uses the value as given.
    """
    if is_grid and not value:
        return True
    try:
        periods.period(str(value))
    except ValueError:
        return False
    return True


def _describe(value: object) -> str:
    """Describe a received JSON value for an error message."""
    if value is _MISSING:
        description = "missing"
    elif isinstance(value, list):
        description = "a list" if value else "an empty list"
    elif isinstance(value, dict):
        description = "an object"
    elif isinstance(value, str) and len(value) > _MAX_QUOTED_STRING_LENGTH:
        description = "a string"
    else:
        # null, a boolean, a number or a short string, written as JSON writes it
        description = json.dumps(value)
    return description
