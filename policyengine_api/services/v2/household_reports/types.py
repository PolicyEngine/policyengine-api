"""The Simulation Entrypoint's household report routes, as the Public API uses them.

A household report calculates one stored household under a baseline and,
optionally, a reform, each a stored policy or current law, for the
household's ``default_year``. The Simulation Entrypoint owns household
reports: their definitions, runs and calculated households live in its
database, and it reads the household and the policies from the Public API's
tables itself. ``HouseholdReportSimulation`` is those routes, with the
records they answer; they raise the errors of
``policyengine_api.services.v2.simulation_entrypoint.types``.
``policyengine_api.libs.simulation_household_reports`` implements it with the
generated simulation client, and tests replace it with a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from policyengine_api.query_parameters import ResourceId

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.services.v2.simulation_entrypoint.types import (
        JSONObject,
        ReportStatus,
        RunTrigger,
    )


class StrictHouseholdReportInput(BaseModel):
    """Reject fields outside the reviewed household report contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class HouseholdPolicyChoice(StrictHouseholdReportInput):
    """A stored v2 policy of the report's country, or none for current law."""

    policy_id: ResourceId | None = None


class HouseholdReportFields(StrictHouseholdReportInput):
    """What a household report calculates, apart from its country.

    ``household_id`` names a household stored through ``/v2/households``.
    ``reform`` is null for a report of the baseline alone. The report is for
    the household's ``default_year``.
    """

    kind: Literal["household"]
    household_id: ResourceId
    baseline: HouseholdPolicyChoice
    reform: HouseholdPolicyChoice | None = None


@dataclass(frozen=True)
class HouseholdReportSubmission:
    """A new household report as the Simulation Entrypoint is asked to create it.

    ``policyengine_version`` selects the country's catalog version.
    """

    country_id: str
    policyengine_version: str
    household_id: UUID
    baseline: HouseholdPolicyChoice
    reform: HouseholdPolicyChoice | None


@dataclass(frozen=True)
class HouseholdCalculationError:
    """Why a household calculation failed.

    ``code`` is the run's error code, such as ``household_calculation_failed``,
    when the household function refused the inputs; ``detail`` then holds its
    error, with the Public API's error codes and messages.
    """

    code: str
    message: str
    detail: JSONObject | None


@dataclass(frozen=True)
class HouseholdCalculationOutput:
    """A succeeded calculation: the household with its requested values filled in.

    ``household`` keeps the stored household's key order. ``spm_config`` is
    the SPM selection applied and ``spm_provenance`` its receipt, both None
    for a country without SPM.
    """

    household: JSONObject
    warnings: tuple[str, ...]
    spm_config: JSONObject | None
    spm_provenance: JSONObject | None


@dataclass(frozen=True)
class HouseholdCalculationRecord:
    """One calculation of the household under one policy: a simulation run.

    ``status`` is ``pending``, ``dispatching``, ``running``, ``succeeded`` or
    ``failed``; ``attempt`` counts forced recalculations. ``result`` is set
    once it succeeded and ``error`` once it failed.
    """

    id: UUID
    simulation_id: UUID
    policy_id: UUID | None
    status: str
    attempt: int
    trigger: str
    error: HouseholdCalculationError | None
    result: HouseholdCalculationOutput | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class HouseholdReportRunRecord:
    """One calculation of a household report: the baseline's and the reform's.

    ``tax_benefit_model_version_id`` is the catalog version it ran on and
    ``policyengine_version`` that version's PolicyEngine.py version: the one
    the Public API sent, for a run it just started, or the one its own
    catalog records, for a run read back (None if the catalog lacks it).
    ``reform`` is None for a report of the baseline alone.
    """

    id: UUID
    report_id: UUID
    trigger: str
    tax_benefit_model_version_id: UUID
    policyengine_version: str | None
    year: int
    status: ReportStatus
    baseline: HouseholdCalculationRecord
    reform: HouseholdCalculationRecord | None


@dataclass(frozen=True)
class HouseholdReportRecord:
    """A household report with its newest run, or the run a request started.

    ``status`` is the run's, or ``not_run`` before the first run, when
    ``household_id`` is not known either.
    """

    id: UUID
    country_id: str
    year: int
    household_id: UUID | None
    baseline_simulation_id: UUID
    reform_simulation_id: UUID | None
    status: ReportStatus
    run: HouseholdReportRunRecord | None


class HouseholdReportSimulation(Protocol):
    """The Simulation Entrypoint's household report routes.

    Every method raises ``SimulationServiceUnavailableError`` when the
    entrypoint cannot be used.
    """

    def submit_report(
        self, submission: HouseholdReportSubmission
    ) -> HouseholdReportRecord:
        """Create the report and its first run, and start it.

        Raise ``SimulationRequestRefusedError`` when the entrypoint refuses the
        caller's data, with its reason.
        """
        ...

    def get_report(self, report_id: UUID) -> HouseholdReportRecord:
        """Return a report; raise ``SimulationRecordNotFoundError`` if unknown."""
        ...

    def run_report(
        self,
        report_id: UUID,
        *,
        policyengine_version: str,
        trigger: RunTrigger,
        force: bool,
    ) -> HouseholdReportRecord:
        """Start another run on the catalog version of ``policyengine_version``.

        Return the report with the new run. Runs that are unfinished or
        succeeded within the last 28 days are reused unless ``force`` is set.
        Raise ``SimulationRecordNotFoundError`` for an unknown report and
        ``SimulationRequestRefusedError`` when the entrypoint refuses the
        caller's data.
        """
        ...


class StoredHousehold(Protocol):
    """A household stored through ``/v2/households``, as far as a report needs it."""

    @property
    def default_year(self) -> int | None:
        """The year the household's values name, which a report calculates."""
        ...


class HouseholdSource(Protocol):
    """Read stored households, as ``/v2/households`` does (``V2HouseholdService``)."""

    def get_household(self, *, country_id: str, household_id: UUID) -> StoredHousehold:
        """Return the country's household, or raise ``HouseholdNotFoundError``."""
        ...


class PolicySource(Protocol):
    """Read stored policies, as ``/v2/policies`` does (``V2PolicyService``)."""

    def get_policy(self, *, country_id: str, policy_id: UUID) -> object:
        """Return the country's policy, or raise ``PolicyNotFoundError``."""
        ...
