"""What the Public API asks the simulation service, and how the service answers.

The simulation service creates simulations, reports and their runs in the
detailed-save tables, and starts their calculation on Modal. Its
``POST /simulations`` and ``POST /reports`` are reached through
``SimulationServiceClient``; ``policyengine_api.libs.simulation_reports``
implements it over HTTP, and tests replace it with a stand-in. Reading what
it created needs no call: the Public API reads the tables.

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

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from pydantic.json_schema import SkipJsonSchema

from policyengine_api.query_parameters import CountryId, ResourceId
from policyengine_api.spm import SPMSelection

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.countries.types import CountryRead
    from policyengine_api.services.v2.households.types import HouseholdRead
    from policyengine_api.services.v2.policies.types import CheckedPolicyRead

# The bounds the simulation service and the tables accept.
SimulationYear = Annotated[int, Field(ge=1900, le=2200, description="The year")]
CatalogKey = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^\S+$")]
ReportLabel = Annotated[str, Field(min_length=1, max_length=255)]
ReportDescription = Annotated[str, Field(max_length=10_000)]


class SimulationServiceUnavailableError(RuntimeError):
    """The simulation service could not be asked, or cannot serve the request now.

    It covers a connection never made, a gateway token that cannot be
    fetched, missing configuration, and every answer after which nothing the
    submission asked for runs: a 401, 403, 404, 405, 413 or 429, which the
    gateway, Cloud Run or the service's framework answers before the
    service's route runs; the service's own readable 503; a 400 that
    describes the service's state, or a row the Public API checks first,
    rather than the caller's request (such as a catalog version missing
    while a release deploys); and a 400 or 422 the client cannot read. The
    route answers 503.

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


class EconomyReportFields(StrictSubmissionModel):
    """An economy report: a baseline and a reform simulation of one region's data.

    Both simulations use the report's year, region and dataset, as
    ``EconomySimulationFields`` describes them. ``include_cliffs`` also
    calculates the baseline's and reform's cliff impact. ``spm`` selects the
    SPM forecast scenario and geography; omit it, rather than sending null,
    to use the simulation service's default.
    """

    kind: Literal["economy"]
    label: ReportLabel
    description: ReportDescription | None = None
    year: SimulationYear
    region_code: CatalogKey
    dataset_name: CatalogKey | None = None
    baseline: PolicyChoice
    reform: PolicyChoice
    include_cliffs: StrictBool = False
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


class EconomyReportCreationInput(EconomyReportFields):
    """An economy report to create in the country."""

    country_id: CountryId


class HouseholdPolicyChoice(StrictSubmissionModel):
    """A household simulation's stored policy; none means current law."""

    policy_id: ResourceId | None = None


class HouseholdReportFields(StrictSubmissionModel):
    """A household report: one stored household under a baseline and a reform.

    ``household_id`` names a household stored through ``/v2/households`` in
    the report's country, and both simulations calculate it in ``year``.
    ``reform`` is null, or omitted, for a report of the baseline alone. With
    ``add_missing_variables``, each simulation also calculates every yearly,
    monthly and eternal variable the household lacks, as ``/calculate-full``
    does; otherwise it fills in only the values the household asks for.
    """

    kind: Literal["household"]
    label: ReportLabel
    description: ReportDescription | None = None
    household_id: ResourceId
    year: SimulationYear
    baseline: HouseholdPolicyChoice
    reform: HouseholdPolicyChoice | None = None
    add_missing_variables: StrictBool = False


class HouseholdReportCreationInput(HouseholdReportFields):
    """A household report to create in the country."""

    country_id: CountryId


# A report of any kind to create; ``kind`` says which.
ReportCreationInput = EconomyReportCreationInput | HouseholdReportCreationInput


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

    ``SimulationSubmissionService``, which checks a submission before sending
    it through a client, also raises EconomyCalculationsUnsupportedError,
    HouseholdCalculationsUnsupportedError, HouseholdNotFoundError,
    PolicyNotFoundError, PolicyParametersMissingError and
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


class CountrySource(Protocol):
    """The countries list a submission checks first."""

    def list_countries(self) -> list[CountryRead]:
        """Return every served country and what it supports."""
        ...


class HouseholdSource(Protocol):
    """The stored households a household report names (``V2HouseholdService``)."""

    def get_household(self, *, country_id: str, household_id: UUID) -> HouseholdRead:
        """Return the country's household, or raise ``HouseholdNotFoundError``."""
        ...


class PolicySource(Protocol):
    """The stored policies a submission names."""

    def get_policy(self, *, country_id: str, policy_id: UUID) -> CheckedPolicyRead:
        """Return the country's policy, or raise ``PolicyNotFoundError``."""
        ...
