"""Framework-independent data exchanged by the household calculation layers."""

from __future__ import annotations

import math
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from policyengine_api.query_parameters import CountryId
from policyengine_api.spm import SPMSelection

# The simulation service's limits on axes, as its household contract sets
# them: at most MAXIMUM_AXIS_GROUPS groups of at most MAXIMUM_PARALLEL_AXES
# axes each, and at most MAXIMUM_AXIS_POINTS points in the grid the groups
# form (the product of their point counts).
MAXIMUM_AXIS_POINTS = 10_000
MAXIMUM_AXIS_GROUPS = 8
MAXIMUM_PARALLEL_AXES = 32


class StrictCalculationModel(BaseModel):
    """Base for household calculation input: no unknown fields, finite numbers."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class HouseholdCalculationAxis(StrictCalculationModel):
    """One input varied across points.

    The variable ``name`` takes ``count`` evenly spaced values from ``min`` to
    ``max`` in ``period`` (the household's ``default_year`` when omitted), for
    the entity member at position ``index`` (the first when omitted).
    """

    name: Annotated[str, Field(min_length=1, max_length=255)]
    count: Annotated[int, Field(ge=1, le=MAXIMUM_AXIS_POINTS)]
    min: int | float
    max: int | float
    period: Annotated[str, Field(min_length=1, max_length=64)] | int | None = None
    index: Annotated[int, Field(ge=0)] | None = None


AxisGroup = Annotated[
    list[HouseholdCalculationAxis],
    Field(min_length=1, max_length=MAXIMUM_PARALLEL_AXES),
]


def _omit_spm_default(schema: dict[str, Any]) -> None:
    # Omitting spm sends no SPM settings; an explicit null is not a selection.
    schema.pop("default", None)


class HouseholdCalculationInput(StrictCalculationModel):
    """A stored household to calculate under a stored policy, or current law.

    The calculation's year is the household's default year, the year its
    values name. ``axes`` vary inputs across points: the axes of one group
    vary together, so they share one point count, and the groups form a grid
    of at most 10,000 points. ``add_missing_variables`` adds every yearly,
    monthly and eternal variable the household lacks, as ``/calculate-full``
    does. ``spm`` selects the SPM forecast scenario and geography for this
    calculation; omit it, rather than sending null, to send no settings.
    """

    country_id: CountryId
    household_id: UUID
    policy_id: UUID | None = None
    axes: Annotated[list[AxisGroup], Field(max_length=MAXIMUM_AXIS_GROUPS)] | None = (
        None
    )
    add_missing_variables: bool = False
    spm: SPMSelection | SkipJsonSchema[None] = Field(
        default=None, json_schema_extra=_omit_spm_default
    )

    @field_validator("axes")
    @classmethod
    def limit_axis_points(
        cls, axes: list[list[HouseholdCalculationAxis]] | None
    ) -> list[list[HouseholdCalculationAxis]] | None:
        """Refuse groups of uneven point counts and grids of too many points."""
        if axes is None:
            return None
        for group in axes:
            if len({axis.count for axis in group}) != 1:
                msg = "the axes of one group must share one point count"
                raise ValueError(msg)
        if math.prod(group[0].count for group in axes) > MAXIMUM_AXIS_POINTS:
            msg = f"the axis groups may vary at most {MAXIMUM_AXIS_POINTS} points"
            raise ValueError(msg)
        return axes

    @field_validator("spm", mode="before")
    @classmethod
    def require_spm_object(cls, value: object) -> object:
        """Refuse an explicit null ``spm``; omit the field to send no settings."""
        if value is None:
            msg = "spm must be an object when supplied"
            raise ValueError(msg)
        return value
