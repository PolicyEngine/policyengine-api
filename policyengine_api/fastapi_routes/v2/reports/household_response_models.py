"""Strict HTTP response models for v2 household reports."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from policyengine_api.services.v2.simulation_entrypoint.types import ReportStatus

if TYPE_CHECKING:
    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportRecord,
        HouseholdReportRunRecord,
    )


class StrictHouseholdReportAPIModel(BaseModel):
    """Strict response base that converts the service's dataclass records."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        from_attributes=True,
    )


class HouseholdReportCalculationErrorItem(StrictHouseholdReportAPIModel):
    """Why a household calculation failed.

    ``code`` is ``household_calculation_failed`` when the household function
    refused the inputs, with its error in ``detail``; ``worker_error``,
    ``worker_timeout`` or ``dispatch_abandoned`` otherwise.
    """

    code: str
    message: str
    detail: dict[str, JsonValue] | None


class HouseholdReportCalculationResultItem(StrictHouseholdReportAPIModel):
    """The household with each requested value filled in, in its own key order.

    ``spm_config`` is the SPM selection applied and ``spm_provenance`` its
    receipt, both null for a country without SPM.
    """

    household: dict[str, JsonValue]
    warnings: list[str]
    spm_config: dict[str, JsonValue] | None
    spm_provenance: dict[str, JsonValue] | None


class HouseholdReportCalculationItem(StrictHouseholdReportAPIModel):
    """One calculation of the household under one policy (a simulation run).

    A null ``policy_id`` means current law. ``status`` is ``pending``,
    ``dispatching``, ``running``, ``succeeded`` or ``failed``; ``attempt``
    counts forced recalculations. ``result`` is set once it succeeded and
    ``error`` once it failed.
    """

    id: UUID
    simulation_id: UUID
    policy_id: UUID | None
    status: str
    attempt: int
    trigger: str
    error: HouseholdReportCalculationErrorItem | None
    result: HouseholdReportCalculationResultItem | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class HouseholdReportRunSummaryItem(StrictHouseholdReportAPIModel):
    """One calculation of a household report, without its calculations.

    ``trigger`` is ``initial`` for the run a submission starts and ``manual``
    for a re-run. ``tax_benefit_model_version_id`` and ``policyengine_version``
    name the catalog version it ran on.
    """

    kind: Literal["household"] = "household"
    id: UUID
    report_id: UUID
    trigger: str
    tax_benefit_model_version_id: UUID
    policyengine_version: str | None
    year: int
    status: ReportStatus


class HouseholdReportRunItem(HouseholdReportRunSummaryItem):
    """One calculation of a household report: the baseline's and the reform's.

    ``reform`` is null for a report of the baseline alone.
    """

    baseline: HouseholdReportCalculationItem
    reform: HouseholdReportCalculationItem | None

    @classmethod
    def from_record(cls, record: HouseholdReportRunRecord) -> HouseholdReportRunItem:
        """Build the response item from the service's report run record."""
        return cls.model_validate(record)


class HouseholdReportSummaryItem(StrictHouseholdReportAPIModel):
    """A household report: a stored household under a baseline and a reform.

    The report is for the household's ``default_year``. ``status`` is the
    newest run's, or ``not_run`` before the first run, when ``household_id`` is
    not known either. ``reform_simulation_id`` is null for a report of the
    baseline alone.
    """

    id: UUID
    country_id: str
    kind: Literal["household"] = "household"
    year: int
    household_id: UUID | None
    baseline_simulation_id: UUID
    reform_simulation_id: UUID | None
    status: ReportStatus
    run: HouseholdReportRunSummaryItem | None

    @classmethod
    def from_record(cls, record: HouseholdReportRecord) -> HouseholdReportSummaryItem:
        """Build the summary from the service's record, without its calculations."""
        return cls.model_validate(record)


class HouseholdReportItem(HouseholdReportSummaryItem):
    """A household report with its newest run and that run's calculations."""

    run: HouseholdReportRunItem | None

    @classmethod
    def from_record(cls, record: HouseholdReportRecord) -> HouseholdReportItem:
        """Build the response item from the service's report record."""
        return cls.model_validate(record)
