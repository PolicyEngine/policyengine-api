"""What the Public API asks the simulation service, and how the service answers.

The simulation service creates simulations, reports and their runs in the
detailed-save tables, and starts their calculation on Modal. Its
``POST /simulations`` and ``POST /reports`` are reached through
``SimulationServiceClient``; ``policyengine_api.libs.simulation_reports``
implements it over HTTP, and tests replace it with a stand-in. Reading what
it created needs no call: the Public API reads the tables.

The simulation service runs every calculation on its default worker's
PolicyEngine.py version, so no request names a version.
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
    from policyengine_api.services.v2.policies.types import CheckedPolicyRead

# The bounds the simulation service and the tables accept.
SimulationYear = Annotated[int, Field(ge=1900, le=2200, description="The year")]
CatalogKey = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^\S+$")]
ReportLabel = Annotated[str, Field(min_length=1, max_length=255)]
ReportDescription = Annotated[str, Field(max_length=10_000)]


class SimulationServiceUnavailableError(RuntimeError):
    """The simulation service could not be asked, or cannot serve the request now.

    That covers a connection never made, a gateway token that cannot be
    fetched, missing configuration, a 400 or 422 that cannot be read, a 400
    that names none of the caller's rows (such as a catalog version missing
    while a release deploys), the service's own readable 503, and a 401,
    403, 404, 405, 413 or 429, which the gateway, Cloud Run or the service's
    framework answers before the service's route runs. The message gives the
    service's status and code, and a 400's reason, but never a 503's reason,
    which may be an exception's text.

    Unless ``created_record_id`` is set, the service has created nothing, and
    submitting again creates one record. ``created_record_id`` is the record
    the service's readable 503 names as the submission's own: when Modal
    refuses the run's call, the service creates the record, fails its run and
    answers 503 with the record's ID. Submitting again then creates a second
    record, but starts no second calculation: the record named has no running
    calculation. A 503 that may follow a record the service created without
    naming it, because it cannot be read or names only another record, is
    SimulationServiceAnswerUnreadableError instead.
    """

    def __init__(self, message: str, *, created_record_id: UUID | None = None) -> None:
        """Say why, and name the record the service created, if it names one."""
        super().__init__(message)
        self.created_record_id = created_record_id


class SimulationServiceAnswerUnreadableError(RuntimeError):
    """The simulation service created the record, or may have, but its answer is lost.

    It answered that it created the simulation or report and started its run,
    but its answer cannot be read; or its answer was lost after the
    submission may have reached it; or a proxy in front of it answered 502 or
    504 in its place; or it answered 503 in a shape that cannot be read,
    which Cloud Run's front end also answers in its place, or naming only a
    record other than the submission's own, which shows it wrote rows; or it
    answered a status the Public API does not expect, which its route may
    answer after writing rows. Submitting again could create another. The
    message gives the service's status and code, never its reason.
    """


class SimulationServiceInternalError(RuntimeError):
    """The simulation service failed (500), possibly after creating the record.

    Submitting again could create another, so this is not reported as the
    service being unavailable. The message gives the status and code, never
    the service's reason, which may be an exception's text.
    """


class SimulationServiceRefusalError(ValueError):
    """The simulation service refused the request's data, and said why.

    For example, a region, dataset or dynamic the catalog version its default
    worker runs does not have. The message gives the service's status, its
    code when it gave one, and its reason, which describes the caller's own
    request.
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

    - SimulationServiceRefusalError when the service refuses the request's
      data (its 422, or its 400 for a region, dataset or dynamic it cannot
      find), with its status, code and reasons;
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
    PolicyNotFoundError and SubmissionStorageError from its checks.
    """

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        """Create the simulation and its first run, and start the run."""
        ...

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        """Create the report, its simulations and their runs, and start them."""
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
