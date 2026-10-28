"""Framework-independent data exchanged by the household calculation layers."""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from policyengine_api.query_parameters import CountryId

if TYPE_CHECKING:
    from collections.abc import Mapping

    from policyengine_api.services.v2.countries.types import CountryRead
    from policyengine_api.services.v2.households.types import HouseholdRead
    from policyengine_api.services.v2.metadata.types import (
        MetadataModelSelectionResult,
    )
    from policyengine_api.services.v2.policies.types import PolicyRead

# The simulation service's limits on axes: the product of the groups' point
# counts is at most MAXIMUM_AXIS_POINTS.
MAXIMUM_AXIS_POINTS = 10_000
MAXIMUM_AXIS_GROUPS = 8
MAXIMUM_PARALLEL_AXES = 32
CalculationStatus = Literal["pending", "dispatching", "running", "succeeded", "failed"]


class StrictCalculationModel(BaseModel):
    """Base for household calculation data: no unknown fields, finite numbers."""

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


class HouseholdCalculationInput(StrictCalculationModel):
    """A stored household to calculate under a stored policy, or current law.

    The calculation's year is the household's default year, the year its
    values name. ``axes`` vary inputs
    across points: the axes of one group vary together, so they share one
    point count, and the groups form a grid of at most 10,000 points.
    ``add_missing_variables`` adds every yearly, monthly and
    eternal variable the household lacks, as ``/calculate-full`` does.
    """

    country_id: CountryId
    household_id: UUID
    policy_id: UUID | None = None
    axes: Annotated[list[AxisGroup], Field(max_length=MAXIMUM_AXIS_GROUPS)] | None = (
        None
    )
    add_missing_variables: bool = False

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


class HouseholdCalculationResult(StrictCalculationModel):
    """A succeeded calculation's household and its notes.

    ``household`` is the stored household in the situation shape, its people
    and groups named by their record IDs, with each requested value filled
    in. ``spm_config`` is the SPM selection the calculation applied and
    ``spm_provenance`` its receipt, both null for a country without SPM.
    """

    household: dict[str, JsonValue]
    warnings: list[str]
    spm_config: dict[str, JsonValue] | None
    spm_provenance: dict[str, JsonValue] | None
    policyengine_version: str | None


class HouseholdCalculationFailure(StrictCalculationModel):
    """Why a calculation failed, with the simulation service's error detail."""

    code: str
    message: str
    detail: dict[str, JsonValue] | None


class HouseholdCalculationRead(StrictCalculationModel):
    """A household calculation as it stands: what it calculates and its outcome."""

    calculation_id: UUID
    country_id: str
    household_id: UUID
    policy_id: UUID | None
    year: int
    catalog_version_id: UUID
    status: CalculationStatus
    created_at: datetime
    completed_at: datetime | None
    result: HouseholdCalculationResult | None
    error: HouseholdCalculationFailure | None

    @classmethod
    def from_simulation(cls, calculation: Mapping[str, Any]) -> Self:
        """Build the read from the simulation service's calculation answer."""
        result = calculation.get("result")
        error = calculation.get("error")
        bundle = result.get("bundle") if isinstance(result, dict) else None
        return cls(
            calculation_id=calculation["calculation_id"],
            country_id=calculation["country"],
            household_id=calculation["household_id"],
            policy_id=calculation["policy_id"],
            year=calculation["year"],
            catalog_version_id=calculation["catalog_version_id"],
            status=calculation["status"],
            created_at=calculation["created_at"],
            completed_at=calculation["completed_at"],
            result=(
                None
                if result is None
                else HouseholdCalculationResult(
                    household=result["household"],
                    warnings=result["warnings"],
                    spm_config=result["spm_config"],
                    spm_provenance=result["spm_provenance"],
                    policyengine_version=(
                        bundle.get("policyengine_version")
                        if isinstance(bundle, dict)
                        else None
                    ),
                )
            ),
            error=None if error is None else HouseholdCalculationFailure(**error),
        )


class SimulationServiceUnavailableError(RuntimeError):
    """The simulation service could not be reached, or could not answer."""


class SimulationServiceRefusedError(RuntimeError):
    """The simulation service refused the calculation; the message says why."""


class SimulationServiceInvalidRequestError(ValueError):
    """The simulation service refuses the caller's data.

    Such as a policy changing a parameter the catalog version lacks, a stored
    policy value or household the household functions cannot take, or an
    invalid option. The message gives the service's reason, or each refused
    field and why.
    """


class CountrySource(Protocol):
    """The countries table (``V2CountryService``)."""

    def list_countries(self) -> list[CountryRead]:
        """Return every served country and its capability."""
        ...


class HouseholdSource(Protocol):
    """Stored households (``V2HouseholdService``)."""

    def get_household(self, *, country_id: str, household_id: UUID) -> HouseholdRead:
        """Return one household of this country, or raise HouseholdNotFoundError."""
        ...


class PolicySource(Protocol):
    """Stored policies (``V2PolicyService``)."""

    def get_policy(self, *, country_id: str, policy_id: UUID) -> PolicyRead:
        """Return one policy of this country, or raise PolicyNotFoundError."""
        ...


class CatalogSource(Protocol):
    """The country's catalog versions (a v2 metadata reader)."""

    def get_model_by_country(self, country_id: str) -> MetadataModelSelectionResult:
        """Return the country's model and the running catalog version."""
        ...

    def close(self) -> None:
        """Close the reader's database session."""
        ...


class SimulationHouseholdCalculations(Protocol):
    """The simulation service's household calculation routes."""

    def submit(self, submission: dict[str, Any]) -> dict[str, Any]:
        """Submit a calculation and return it as the service answers."""
        ...

    def read(self, calculation_id: UUID) -> dict[str, Any] | None:
        """Return the calculation as the service answers, or None if unknown."""
        ...
