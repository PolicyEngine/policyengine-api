"""Framework-independent data exchanged by the household calculation layers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from pydantic.json_schema import SkipJsonSchema

from policyengine_api.query_parameters import CountryId
from policyengine_api.spm import SPMSelection

if TYPE_CHECKING:
    from datetime import datetime

    from policyengine_api.services.v2.countries.types import CountryRead
    from policyengine_api.services.v2.households.types import HouseholdRead
    from policyengine_api.services.v2.policies.types import CheckedPolicyRead

# The simulation service's limits on axes, as its household contract sets
# them: at most MAXIMUM_AXIS_GROUPS groups of at most MAXIMUM_PARALLEL_AXES
# axes each, and at most MAXIMUM_AXIS_POINTS points in the grid the groups
# form (the product of their point counts).
MAXIMUM_AXIS_POINTS = 10_000
MAXIMUM_AXIS_GROUPS = 8
MAXIMUM_PARALLEL_AXES = 32

# A household job's status, as household_jobs stores it: the simulation
# service inserts the job pending, its household function sets it running,
# then succeeded or failed.
HouseholdJobStatusName = Literal["pending", "running", "succeeded", "failed"]


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


@dataclass(frozen=True)
class HouseholdCalculationAccepted:
    """The simulation service's answer to a submission: the new job and its status."""

    calculation_id: UUID
    status: HouseholdJobStatusName


@dataclass(frozen=True)
class HouseholdCalculationSubmitted:
    """A calculation the simulation service accepted, and what it calculates.

    ``year`` is the household's default year, which the simulation service
    calculates.
    """

    calculation_id: UUID
    status: HouseholdJobStatusName
    country_id: str
    household_id: UUID
    policy_id: UUID | None
    year: int


@dataclass(frozen=True)
class HouseholdCalculationOutput:
    """A succeeded calculation's household and its notes.

    ``household`` is the stored household in the situation shape, its people
    and groups named by their record IDs, with each requested value filled
    in, in the order the household function wrote it. ``warnings`` lists the
    inputs the country model ignored. ``spm_config`` is the SPM selection the
    calculation applied and ``spm_provenance`` its receipt, both None for a
    country without SPM.
    """

    household: dict[str, Any]
    warnings: tuple[str, ...]
    spm_config: dict[str, Any] | None
    spm_provenance: dict[str, Any] | None


@dataclass(frozen=True)
class HouseholdCalculationFailure:
    """Why a calculation failed.

    ``code`` is the household function's error code, such as
    ``invalid_inputs``, with ``input_errors`` naming each input the country
    model does not recognize and ``spm_error`` an SPM error. A job that failed
    without the household function's failure document (one whose function
    raised or was cancelled) has no code, and ``message`` is the job's error
    message, such as ``household_function_error: …``.
    """

    code: str | None
    message: str
    input_errors: tuple[dict[str, Any], ...]
    spm_error: dict[str, Any] | None


@dataclass(frozen=True)
class HouseholdCalculationRead:
    """A household calculation as household_jobs records it.

    ``catalog_version_id`` and the package versions are those the simulation
    service ran it with. ``result`` is set once it succeeded and ``error``
    once it failed.
    """

    calculation_id: UUID
    country_id: str
    household_id: UUID
    policy_id: UUID | None
    year: int
    catalog_version_id: UUID
    country_package_version: str
    policyengine_version: str
    status: HouseholdJobStatusName
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: HouseholdCalculationOutput | None
    error: HouseholdCalculationFailure | None


# The result documents the household functions store in household_jobs.result,
# and in simulation_runs.household_result for a household report's simulations.
# The simulation service's household contract owns their shape; these models,
# their two conversions and the household report failure read
# (stored_reports.household_results.transformations) are the only code that
# names its fields.


class StoredDocumentModel(BaseModel):
    """Base for the result documents the household functions store.

    The documents are read only at the household contract's version 1
    (``schema_version``); one of another version, or of none, is refused
    rather than read as version 1. Fields the Public API does not read are
    ignored, so the contract may add some within its version.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)


class StoredCalculationOutput(StoredDocumentModel):
    """A finished calculation of the job's one policy.

    ``household`` is the calculated household, ``warnings`` the inputs the
    country model ignored, ``spm_provenance`` the SPM receipt and
    ``spm_config`` the SPM selection applied, both absent or null without SPM.
    """

    household: dict[str, JsonValue]
    warnings: list[str] = Field(default_factory=list)
    spm_config: dict[str, JsonValue] | None = None
    spm_provenance: dict[str, JsonValue] | None = None


class StoredExecutionResult(StoredDocumentModel):
    """A succeeded job's result document (``HouseholdExecutionResult``)."""

    status: Literal["succeeded"]
    schema_version: Literal[1]
    output: StoredCalculationOutput

    def calculation_output(self) -> HouseholdCalculationOutput:
        """Return the calculated household and its notes."""
        return HouseholdCalculationOutput(
            household=self.output.household,
            warnings=tuple(self.output.warnings),
            spm_config=self.output.spm_config,
            spm_provenance=self.output.spm_provenance,
        )


class StoredCalculationError(StoredDocumentModel):
    """The household function's error, worded as the Public API words it."""

    code: str
    message: str
    input_errors: list[dict[str, JsonValue]] = Field(default_factory=list)
    spm_error: dict[str, JsonValue] | None = None


class StoredExecutionFailure(StoredDocumentModel):
    """A refused job's result document (``HouseholdExecutionFailure``)."""

    status: Literal["failed"]
    schema_version: Literal[1]
    error: StoredCalculationError

    def calculation_failure(self) -> HouseholdCalculationFailure:
        """Return the household function's error."""
        return HouseholdCalculationFailure(
            code=self.error.code,
            message=self.error.message,
            input_errors=tuple(self.error.input_errors),
            spm_error=self.error.spm_error,
        )


class CountrySource(Protocol):
    """The countries table (``V2CountryService``)."""

    def list_countries(self) -> list[CountryRead]:
        """Return every served country and the calculations it supports."""
        ...


class HouseholdSource(Protocol):
    """Stored households (``V2HouseholdService``)."""

    def get_household(self, *, country_id: str, household_id: UUID) -> HouseholdRead:
        """Return one household of this country, or raise HouseholdNotFoundError."""
        ...


class PolicySource(Protocol):
    """Stored policies (``V2PolicyService``)."""

    def get_policy(self, *, country_id: str, policy_id: UUID) -> CheckedPolicyRead:
        """Return one policy of this country, checked against the running catalog.

        Raise PolicyNotFoundError when the country has no such policy.
        """
        ...


class HouseholdCalculationSubmitter(Protocol):
    """The simulation service's ``POST /household-calculations``.

    The simulation service reads the household, the policy's parameter values
    and the catalog version from the Public API's tables itself, inserts the
    job and starts its Modal call.
    """

    def submit(
        self, calculation: HouseholdCalculationInput
    ) -> HouseholdCalculationAccepted:
        """Submit the calculation and return the job the service created.

        Raise, with the error types of
        ``policyengine_api.services.v2.simulation_service.types``,
        SimulationServiceInvalidRequestError when the service refuses the
        caller's data, with its reasons;
        SimulationServiceUnavailableError when no job of the submission will
        run;
        SimulationServiceInternalError when it failed (500), possibly after
        creating the job; and SimulationServiceAnswerUnreadableError when it
        accepted the calculation but its answer cannot be read, it answered a
        status the Public API does not expect, its answer was lost after the
        submission may have reached it, or a proxy in front of it answered
        in its place.
        """
        ...
