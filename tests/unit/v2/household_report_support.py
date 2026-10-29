"""A fake Simulation Entrypoint, stored households and household report records.

The household report service reads countries rows and catalog versions from an
SQLite v2 schema, and stored households and policies through fakes of the
``/v2/households`` and ``/v2/policies`` services.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from policyengine_api.data.v2.models import (
    Country,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.household_reports.database_session import (
    HouseholdReportDatabaseSession,
)
from policyengine_api.services.v2.household_reports.services import (
    V2HouseholdReportService,
)
from policyengine_api.services.v2.household_reports.types import (
    HouseholdCalculationOutput,
    HouseholdCalculationRecord,
    HouseholdReportRecord,
    HouseholdReportRunRecord,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ReportStatus,
    RunTrigger,
    SimulationRecordNotFoundError,
)
from tests.unit.v2.economy_report_support import (
    CURRENT_POLICYENGINE_VERSION,
    countries_store,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportSubmission,
    )

HOUSEHOLD_REPORT_ID = UUID("00000000-0000-4000-8000-000000000301")
HOUSEHOLD_ID = UUID("00000000-0000-4000-8000-000000000302")
HOUSEHOLD_REPORT_RUN_ID = UUID("00000000-0000-4000-8000-000000000303")
BASELINE_CALCULATION_ID = UUID("00000000-0000-4000-8000-000000000304")
REFORM_CALCULATION_ID = UUID("00000000-0000-4000-8000-000000000305")
HOUSEHOLD_CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-000000000306")
OLDER_CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-000000000307")
UNKNOWN_CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-000000000308")
HOUSEHOLD_REFORM_POLICY_ID = UUID("00000000-0000-4000-8000-000000000309")
# A household of the household-only test country.
HOUSEHOLD_ONLY_HOUSEHOLD_ID = UUID("00000000-0000-4000-8000-000000000310")
OLDER_POLICYENGINE_VERSION = "6.5.0"
CALCULATED_AT = datetime(2026, 10, 29, 12, tzinfo=UTC)
CALCULATED_HOUSEHOLD = {
    "people": {"you": {"age": {"2026": 40}, "household_net_income": {"2026": 41250}}},
    "households": {"your household": {"members": ["you"]}},
}


@dataclass(frozen=True)
class StoredHouseholdRow:
    """The part of a stored household the report service reads."""

    id: UUID
    country_id: str
    default_year: int | None


class FakeHouseholds:
    """The ``/v2/households`` service, holding ``households``."""

    def __init__(self, *households: StoredHouseholdRow) -> None:
        self.households = {household.id: household for household in households}

    def get_household(
        self, *, country_id: str, household_id: UUID
    ) -> StoredHouseholdRow:
        household = self.households.get(household_id)
        if household is None or household.country_id != country_id:
            msg = f"Household {household_id} was not found"
            raise HouseholdNotFoundError(msg)
        return household


class FakePolicies:
    """The ``/v2/policies`` service, holding policies by ID and country."""

    def __init__(self, policies: dict[UUID, str]) -> None:
        self.policies = policies

    def get_policy(self, *, country_id: str, policy_id: UUID) -> object:
        if self.policies.get(policy_id) != country_id:
            msg = f"Policy {policy_id} was not found"
            raise PolicyNotFoundError(msg)
        return policy_id


def stored_household(
    *, country_id: str = "us", default_year: int | None = 2026
) -> StoredHouseholdRow:
    return StoredHouseholdRow(
        id=HOUSEHOLD_ID, country_id=country_id, default_year=default_year
    )


def calculation_record(
    calculation_id: UUID,
    simulation_id: UUID,
    policy_id: UUID | None,
    *,
    status: str = "pending",
    trigger: str = "initial",
) -> HouseholdCalculationRecord:
    succeeded = status == "succeeded"
    return HouseholdCalculationRecord(
        id=calculation_id,
        simulation_id=simulation_id,
        policy_id=policy_id,
        status=status,
        attempt=1,
        trigger=trigger,
        error=None,
        result=(
            HouseholdCalculationOutput(
                household=CALCULATED_HOUSEHOLD,
                warnings=(),
                spm_config=None,
                spm_provenance=None,
            )
            if succeeded
            else None
        ),
        dispatched_at=None,
        completed_at=CALCULATED_AT if succeeded else None,
        created_at=CALCULATED_AT,
    )


def household_simulation_ids(report_id: UUID) -> tuple[UUID, UUID]:
    """Return a household report's baseline and reform simulation IDs."""
    return (
        uuid5(NAMESPACE_URL, f"{report_id}/household-baseline"),
        uuid5(NAMESPACE_URL, f"{report_id}/household-reform"),
    )


def household_report_record(
    *,
    report_id: UUID = HOUSEHOLD_REPORT_ID,
    country_id: str = "us",
    status: ReportStatus | None = ReportStatus.PENDING,
    with_reform: bool = True,
    trigger: str = "initial",
) -> HouseholdReportRecord:
    """Build a household report; ``status=None`` means before its first run.

    Each calculation's status is the run's, with a result once it succeeded.
    """
    baseline_id, reform_id = household_simulation_ids(report_id)
    run = None
    if status is not None:
        calculation_status = (
            "running" if status is ReportStatus.RUNNING else status.value
        )
        run = HouseholdReportRunRecord(
            id=HOUSEHOLD_REPORT_RUN_ID,
            report_id=report_id,
            trigger=trigger,
            tax_benefit_model_version_id=HOUSEHOLD_CATALOG_VERSION_ID,
            policyengine_version=None,
            year=2026,
            status=status,
            baseline=calculation_record(
                BASELINE_CALCULATION_ID,
                baseline_id,
                None,
                status=calculation_status,
                trigger=trigger,
            ),
            reform=(
                calculation_record(
                    REFORM_CALCULATION_ID,
                    reform_id,
                    HOUSEHOLD_REFORM_POLICY_ID,
                    status=calculation_status,
                    trigger=trigger,
                )
                if with_reform
                else None
            ),
        )
    return HouseholdReportRecord(
        id=report_id,
        country_id=country_id,
        year=2026,
        household_id=None if run is None else HOUSEHOLD_ID,
        baseline_simulation_id=baseline_id,
        reform_simulation_id=reform_id if with_reform else None,
        status=ReportStatus.NOT_RUN if run is None else run.status,
        run=run,
    )


def on_catalog_version(
    report: HouseholdReportRecord, catalog_version_id: UUID
) -> HouseholdReportRecord:
    """Return the report with its run on another catalog version."""
    if report.run is None:
        return report
    return replace(
        report,
        run=replace(report.run, tax_benefit_model_version_id=catalog_version_id),
    )


class FakeHouseholdReportSimulation:
    """An in-memory Simulation Entrypoint for household reports.

    ``reports`` holds what it knows and ``calls`` records every call; ``error``
    is raised by every call while set. A submission or a run answers with
    ``next_status`` and ``next_catalog_version_id``.
    """

    def __init__(self, *reports: HouseholdReportRecord) -> None:
        self.reports = {report.id: report for report in reports}
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None
        self.next_status = ReportStatus.PENDING
        self.next_catalog_version_id = HOUSEHOLD_CATALOG_VERSION_ID

    def _record(self, name: str, argument: object) -> None:
        self.calls.append((name, argument))
        if self.error is not None:
            raise self.error

    def _on_next_catalog_version(
        self, report: HouseholdReportRecord
    ) -> HouseholdReportRecord:
        return on_catalog_version(report, self.next_catalog_version_id)

    def submit_report(
        self, submission: HouseholdReportSubmission
    ) -> HouseholdReportRecord:
        self._record("submit_report", submission)
        report = self._on_next_catalog_version(
            household_report_record(
                country_id=submission.country_id,
                status=self.next_status,
                with_reform=submission.reform is not None,
            )
        )
        self.reports[report.id] = report
        return report

    def get_report(self, report_id: UUID) -> HouseholdReportRecord:
        self._record("get_report", report_id)
        if report_id not in self.reports:
            msg = "No such household report."
            raise SimulationRecordNotFoundError(msg)
        return self.reports[report_id]

    def run_report(
        self,
        report_id: UUID,
        *,
        policyengine_version: str,
        trigger: RunTrigger,
        force: bool,
    ) -> HouseholdReportRecord:
        self._record(
            "run_report",
            {
                "report_id": report_id,
                "policyengine_version": policyengine_version,
                "trigger": trigger,
                "force": force,
            },
        )
        stored = self.reports.get(report_id)
        if stored is None:
            msg = "No such household report."
            raise SimulationRecordNotFoundError(msg)
        report = self._on_next_catalog_version(
            household_report_record(
                report_id=report_id,
                country_id=stored.country_id,
                status=self.next_status,
                with_reform=stored.reform_simulation_id is not None,
                trigger=trigger.value,
            )
        )
        self.reports[report_id] = report
        return report


def household_report_store() -> sessionmaker[Session]:
    """Build the countries rows and two US catalog versions.

    Besides the US and UK, ``zz`` has only household calculations and ``xx``
    has neither household calculations nor economy reports. The catalog
    versions are the current one and an older one.
    """
    # New row objects: a row object another store committed is not inserted again.
    sessions = countries_store(
        Country(id="zz", household_enabled=True, society_wide_enabled=False),
        Country(id="xx", household_enabled=False, society_wide_enabled=False),
    )
    with sessions() as session:
        model = TaxBenefitModel(name="policyengine-us")
        session.add(model)
        session.flush()
        session.add_all(
            TaxBenefitModelVersion(
                id=version_id,
                model_id=model.id,
                version=version,
                current_law_id=1,
                metadata_time_periods=[2026],
            )
            for version_id, version in (
                (HOUSEHOLD_CATALOG_VERSION_ID, CURRENT_POLICYENGINE_VERSION),
                (OLDER_CATALOG_VERSION_ID, OLDER_POLICYENGINE_VERSION),
            )
        )
        session.commit()
    return sessions


def set_country_support(
    sessions: sessionmaker[Session],
    country_id: str,
    *,
    household_enabled: bool,
    society_wide_enabled: bool,
) -> None:
    """Change what a stored country supports, as for a household-only country."""
    with sessions() as session:
        country = session.get(Country, country_id)
        assert country is not None
        country.household_enabled = household_enabled
        country.society_wide_enabled = society_wide_enabled
        session.commit()


def household_report_service(
    simulation: FakeHouseholdReportSimulation,
    *,
    households: FakeHouseholds | None = None,
    policies: FakePolicies | None = None,
    sessions: sessionmaker[Session] | None = None,
) -> V2HouseholdReportService:
    return V2HouseholdReportService(
        HouseholdReportDatabaseSession(
            household_report_store() if sessions is None else sessions
        ),
        households=(
            FakeHouseholds(
                stored_household(),
                replace(
                    stored_household(country_id="zz"), id=HOUSEHOLD_ONLY_HOUSEHOLD_ID
                ),
            )
            if households is None
            else households
        ),
        policies=(
            FakePolicies({HOUSEHOLD_REFORM_POLICY_ID: "us"})
            if policies is None
            else policies
        ),
        simulation=simulation,
        current_policyengine_version=CURRENT_POLICYENGINE_VERSION,
    )
