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
    """The simulation service could not be asked, or did not answer as expected.

    That covers no answer, an answer of another shape, a gateway token that
    cannot be fetched, missing configuration and the service's own
    unavailability.
    """


class SimulationServiceAnswerUnreadableError(RuntimeError):
    """The simulation service created the record, but its answer is unreadable.

    It answered that it created the simulation or report and started its run,
    so submitting again would create another.
    """


class SimulationServiceInternalError(RuntimeError):
    """The simulation service failed (500), possibly after creating the record.

    Submitting again could create another, so this is not reported as the
    service being unavailable.
    """


class SimulationServiceRefusalError(ValueError):
    """The simulation service refused the request's data, and said why.

    For example, a region, dataset or dynamic the current catalog version
    does not have.
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

    Each raises SimulationServiceRefusalError when the service refuses the
    request's data, and SimulationServiceUnavailableError otherwise.
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
