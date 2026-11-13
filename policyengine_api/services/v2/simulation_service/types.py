"""What the Public API asks the simulation service, and how the service answers.

The simulation service creates simulations, reports and their runs in the
detailed-save tables, and starts their calculation on Modal. Its
``POST /simulations``, ``POST /reports`` and ``POST
/reports/{report_id}/runs``, which runs a stored report again, are reached
through ``SimulationServiceClient``;
``policyengine_api.libs.simulation_reports`` implements it over HTTP, and
tests replace it with a stand-in. Reading what it created needs no call: the
Public API reads the tables.

The simulation service runs every calculation on its default worker's
PolicyEngine.py version, so no request names a version.

The ``SimulationService*Error`` types are the simulation service's failures
for every v2 route that calls it: household calculations
(``policyengine_api.libs.simulation_household_calculations``) as well as
reports and simulations. Each client's module docstring lists which of its
service's answers it raises as which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from policyengine_api.data.v2.models.reports import LAST_YEAR, MAX_BUDGET_WINDOW_YEARS
from policyengine_api.query_parameters import CountryId, ResourceId
from policyengine_api.spm import SPMSelection

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.countries.types import CountryRead
    from policyengine_api.services.v2.policies.types import CheckedPolicyRead

# The bounds the simulation service and the tables accept.
SimulationYear = Annotated[int, Field(ge=1900, le=2200, description="The year")]
CatalogKey = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^\S+$")]
ReportLabel = Annotated[str, Field(min_length=1, max_length=255)]
ReportDescription = Annotated[str, Field(max_length=10_000)]
WindowFirstYear = Annotated[
    int, Field(ge=1900, le=LAST_YEAR, description="The window's first year")
]
BudgetWindowSize = Annotated[
    int,
    Field(
        ge=1,
        le=MAX_BUDGET_WINDOW_YEARS,
        description="How many consecutive years the window has, from its year",
    ),
]


class SimulationServiceUnavailableError(RuntimeError):
    """The simulation service could not be asked, or cannot serve the request now.

    It covers a connection never made, a gateway token that cannot be
    fetched, missing configuration, and every answer after which nothing the
    submission asked for runs: a 401, 403, 404, 405, 413 or 429, which the
    gateway, Cloud Run or the service's framework answers before the
    service's route runs; the service's own readable 503; a 400 that
    describes the service's state, or a row the Public API checks first,
    rather than the caller's request (such as a catalog version missing
    while a release deploys); a 400 or 422 the client cannot read; and a
    re-run's 409 the client cannot read, which the service answers only
    before writing anything. The route answers 503.

    A message gives the service's reason only for a readable 400. For any
    other answer it gives the status, and the code when that is a fixed
    identifier, but never the reason, which for a 503 may be an exception's
    text.

    Unless ``created_record_id`` is set, the service has created nothing
    that will run, and submitting again creates one record or job.
    ``created_record_id`` is the report or simulation the service's readable
    503 names as the submission's own: when Modal refuses the run's call,
    the service creates the record, fails its run and answers 503 with the
    record's ID. Submitting again then creates a second record, but starts
    no second calculation: the record named has no running calculation. A
    503 that may follow a record the service created without naming it is
    SimulationServiceAnswerUnreadableError instead. A household
    calculation's 503 never names its job, which the service fails at once.
    """

    def __init__(self, message: str, *, created_record_id: UUID | None = None) -> None:
        """Say why, and name the record the service created, if it names one."""
        super().__init__(message)
        self.created_record_id = created_record_id


class SimulationServiceAnswerUnreadableError(RuntimeError):
    """The service created what was submitted, or may have, but gave no usable answer.

    It answered that it created the household job, simulation or report,
    but its answer cannot be read; or its answer was lost after the
    submission may have reached it; or a proxy in front of it answered in
    its place (a 502 or 504, or a 503 the client reads as a proxy's). Despite
    the name, it also covers answers that can be read but leave open whether
    something was created: any status the Public API does not expect, which
    the service's route may answer after writing rows, and a report's or
    simulation's 503 naming only another record, which shows the service
    wrote rows. Submitting again could create another, so the route answers
    502. A message naming the service's status gives its code only when that
    is a fixed identifier, and never its reason.
    """


class SimulationServiceInternalError(RuntimeError):
    """The simulation service failed (500), possibly after creating what was submitted.

    The household job, simulation or report may already exist, so submitting
    again may create a second one; this is why it is not reported as the
    service being unavailable, and the route answers 502. The message gives
    the status, and the code when that is a fixed identifier, but never the
    service's reason, which may be an exception's text, and asks the caller
    to submit again.
    """


class SimulationServiceInvalidRequestError(ValueError):
    """The simulation service refused the caller's data, and said why.

    Such as a stored household or policy value its household contract cannot
    take, an option it refuses, or a region, dataset or dynamic the catalog
    version its default worker runs does not have. The message gives the
    service's reasons, which describe the caller's own request, and, for a
    report or simulation, the code the service gave, but not the service's
    status. The route answers 422.
    """


class SimulationServiceConflictError(RuntimeError):
    """The simulation service will not run the stored report again now.

    The report has a run pending or running, which ``run_id`` names, or it is
    one the service does not run again, such as a kind of report it cannot
    re-run yet or one whose simulation, region or dataset is gone. The
    service wrote nothing. The message gives the service's code and reason;
    the route answers 409, naming ``run_id`` when the service named a run.
    """

    def __init__(self, message: str, *, run_id: UUID | None = None) -> None:
        """Say why, and name the run under way, if the service named one."""
        super().__init__(message)
        self.run_id = run_id


@dataclass(frozen=True)
class PackageVersions:
    """A country package version and the PolicyEngine.py version beside it."""

    country_package_version: str
    policyengine_version: str


class StrictSubmissionModel(BaseModel):
    """Base for submissions: no unknown fields, finite numbers, immutable."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class PolicyChoice(StrictSubmissionModel):
    """A simulation's stored policy and dynamic; neither means current law."""

    policy_id: ResourceId | None = None
    dynamic_id: ResourceId | None = None


class EconomySimulationFields(PolicyChoice):
    """An economy simulation: a policy and dynamic applied to one region's data.

    ``region_code`` is a region of the country's current catalog version
    (``us``, ``state/ca``, ``country/wales``), and ``dataset_name`` one of its
    datasets; without it the region's default dataset is used.
    """

    kind: Literal["economy"]
    year: SimulationYear
    region_code: CatalogKey
    dataset_name: CatalogKey | None = None


class EconomySimulationCreationInput(EconomySimulationFields):
    """An economy simulation to create in the country."""

    country_id: CountryId


def _omit_spm_default(schema: dict[str, Any]) -> None:
    # Omitting spm sends no SPM settings; an explicit null is not a selection.
    schema.pop("default", None)


class ReportDefinitionFields(StrictSubmissionModel):
    """What every report names: a label, and a baseline and a reform simulation.

    Both simulations use the report's year (a budget window's first year;
    each later year gets simulations of its own), region and dataset, as
    ``EconomySimulationFields`` describes them. ``spm`` selects the SPM
    forecast scenario and geography; omit it, rather than sending null, to
    use the simulation service's default. Each kind of report narrows
    ``kind`` and adds its own fields.
    """

    kind: Literal["economy", "budget_window"]
    label: ReportLabel
    description: ReportDescription | None = None
    year: SimulationYear
    region_code: CatalogKey
    dataset_name: CatalogKey | None = None
    baseline: PolicyChoice
    reform: PolicyChoice
    spm: SPMSelection | SkipJsonSchema[None] = Field(
        default=None, json_schema_extra=_omit_spm_default
    )

    @field_validator("spm", mode="before")
    @classmethod
    def require_spm_object(cls, value: object) -> object:
        """Refuse an explicit null ``spm``; omit the field to send no settings."""
        if value is None:
            msg = "spm must be an object when supplied"
            raise ValueError(msg)
        return value


class EconomyReportFields(ReportDefinitionFields):
    """An economy report: a baseline and a reform simulation of one region's data.

    ``include_cliffs`` also calculates the baseline's and reform's cliff
    impact; the other fields are as ``ReportDefinitionFields`` describes
    them.
    """

    kind: Literal["economy"]
    include_cliffs: StrictBool = False


class EconomyReportCreationInput(EconomyReportFields):
    """An economy report to create in the country."""

    country_id: CountryId


class HouseholdPolicyChoice(StrictSubmissionModel):
    """A household simulation's stored policy; none means current law."""

    policy_id: ResourceId | None = None


class HouseholdReportFields(StrictSubmissionModel):
    """A household report: one stored household under a baseline and a reform.

    ``household_id`` names a household stored through ``/v2/households`` in
    the report's country, and both simulations calculate it in its default
    year, the year its values name, as a household calculation does.
    ``reform`` is null, or omitted, for a report of the baseline alone. Each
    simulation calculates every yearly, monthly and eternal variable the
    household lacks, as ``/calculate-full`` does, so the report gives every
    value; there is no option to fill in only the values the household asks
    for, as ``/v2/household-calculations`` has.
    """

    kind: Literal["household"]
    label: ReportLabel
    description: ReportDescription | None = None
    household_id: ResourceId
    baseline: HouseholdPolicyChoice
    reform: HouseholdPolicyChoice | None = None


class HouseholdReportCreationInput(HouseholdReportFields):
    """A household report to create in the country."""

    country_id: CountryId


class BudgetWindowReportFields(ReportDefinitionFields):
    """A budget window: a baseline and a reform simulation in each of several years.

    The window is ``budget_window_size`` consecutive years from ``year``,
    ending in 2200 or earlier. Each year compares the two simulations of one
    region's data in that year, as an economy report does; the other fields
    are as ``ReportDefinitionFields`` describes them. Cliff impacts are not
    calculated for a budget window, so it takes no ``include_cliffs``.
    """

    kind: Literal["budget_window"]
    year: WindowFirstYear
    budget_window_size: BudgetWindowSize

    @model_validator(mode="after")
    def require_window_within_the_years_stored(self) -> BudgetWindowReportFields:
        """Refuse a window whose last year is after 2200."""
        if self.year + self.budget_window_size - 1 > LAST_YEAR:
            msg = f"a budget window must end in {LAST_YEAR} or earlier"
            raise ValueError(msg)
        return self


class BudgetWindowReportCreationInput(BudgetWindowReportFields):
    """A budget window to create in the country."""

    country_id: CountryId


# A report of any kind to create; ``kind`` says which.
ReportCreationInput = (
    EconomyReportCreationInput
    | HouseholdReportCreationInput
    | BudgetWindowReportCreationInput
)


@dataclass(frozen=True)
class SubmittedSimulation:
    """The simulation the simulation service created, and the run it started."""

    simulation_id: UUID
    simulation_run_id: UUID


@dataclass(frozen=True)
class SubmittedReport:
    """The report the simulation service created, and the run it started."""

    report_id: UUID
    report_run_id: UUID


@dataclass(frozen=True)
class SubmittedBudgetWindow:
    """The budget window the simulation service created, and its first run.

    ``budget_window_run_id`` is the budget-window run, whose years the
    service created and started.
    """

    report_id: UUID
    budget_window_run_id: UUID


# Each kind of stored report a re-run names, as the report's row records it.
ReportRerunKind = Literal["economy", "household", "budget_window"]


@dataclass(frozen=True)
class ReportRerunInput:
    """A stored report of the country to calculate again as a new run.

    The simulation service runs it on its default worker's versions. Without
    ``force``, each side reuses a run of its own simulation that succeeded on
    those versions; with it, both simulations are calculated again.
    ``kind`` is the report's, which picks the country check: a household
    report's country must have household calculations, any other report's
    economy calculations. ``policy_ids`` are the policies of the report's
    simulations, baseline first, None for current law, a report of the
    baseline alone or a simulation that is gone, for the checks before the
    simulation service is asked.
    """

    country_id: str
    report_id: UUID
    kind: ReportRerunKind
    force: bool
    policy_ids: tuple[UUID | None, ...]


class SimulationServiceClient(Protocol):
    """The simulation service's routes that create and start calculations.

    Each raises:

    - SimulationServiceInvalidRequestError when the service refuses the
      request's data (its 422, or its 400 for a region, dataset or dynamic it
      cannot find), with its code and reasons;
    - SimulationServiceInternalError when it failed (500), possibly after
      creating the record;
    - SimulationServiceAnswerUnreadableError when it created the record but
      its answer cannot be read, its answer was lost after the submission may
      have reached it, a proxy answered 502 or 504 in its place, it answered
      503 in a shape that cannot be read or naming only another record, or
      it answered a status the client does not expect, which its route may
      answer after writing rows;
    - SimulationServiceUnavailableError otherwise: a connection never made, a
      gateway token that cannot be fetched, missing configuration, a 400 or
      422 that cannot be read, any other 400, its readable 503, or a 401,
      403, 404, 405, 413 or 429, sent before its route runs. It names the
      record the service created when the service's 503 names the
      submission's own.

    ``rerun_report`` raises the same errors, apart from naming a created
    record, and SimulationServiceConflictError when the service will not run
    the report again now; a 409 that cannot be read is
    SimulationServiceUnavailableError, since the service answers 409 only
    before writing anything.

    ``SimulationSubmissionService``, which checks a submission before sending
    it through a client, also raises EconomyCalculationsUnsupportedError,
    HouseholdCalculationCountryError, HouseholdNotFoundError,
    HouseholdCalculationYearError, PolicyNotFoundError,
    PolicyParametersMissingError and
    SubmissionStorageError from its checks.
    """

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        """Create the simulation and its first run, and start the run."""
        ...

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        """Create the report, its simulations and their runs, and start them."""
        ...

    def submit_household_report(
        self, report: HouseholdReportCreationInput
    ) -> SubmittedReport:
        """Create the household report, its simulations and runs; start them.

        It goes to the same route as ``submit_report``, so it raises the same
        errors.
        """
        ...

    def submit_budget_window(
        self, report: BudgetWindowReportCreationInput
    ) -> SubmittedBudgetWindow:
        """Create the budget window, its simulations and a run per year; start them.

        It goes to the same route as ``submit_report``, so it raises the same
        errors.
        """
        ...

    def rerun_report(self, rerun: ReportRerunInput) -> None:
        """Create the stored report's new run on the current versions, and start it."""
        ...


class CountrySource(Protocol):
    """The countries list a submission checks first."""

    def list_countries(self) -> list[CountryRead]:
        """Return every served country and what it supports."""
        ...


class PolicySource(Protocol):
    """The stored policies a submission names."""

    def get_policy(self, *, country_id: str, policy_id: UUID) -> CheckedPolicyRead:
        """Return the country's policy, or raise ``PolicyNotFoundError``."""
        ...
