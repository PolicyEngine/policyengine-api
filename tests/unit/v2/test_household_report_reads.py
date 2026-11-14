"""Read household reports and their calculated households from the v2 tables.

The tables are SQLite's copy of the v2 schema. Each household report's two
simulations calculate one stored household; once the newest report run has
succeeded, each simulation run's ``household_result`` holds the household
function's result document, which the read returns as the report's result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Household,
    Policy,
    Report,
    ReportRun,
    ReportRunStatus,
    ReportRunTrigger,
    Simulation,
    SimulationRun,
    SimulationStatus,
    SimulationType,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationOutput,
)
from policyengine_api.services.v2.simulation_service.types import (
    HouseholdReportCreationInput,
    PackageVersions,
    SubmittedReport,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.household_results.types import (
    HouseholdReportFailure,
    HouseholdReportResult,
    HouseholdReportSideFailure,
    HouseholdResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from policyengine_api.services.v2.stored_reports.types import (
    HouseholdReportRead,
    HouseholdReportSummaryRead,
    ReportSummaryRead,
)
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
    StoredReportNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

STORED_AT = datetime(2026, 11, 13, 9, tzinfo=UTC)
CURRENT_VERSIONS = PackageVersions(
    country_package_version="1.5.0", policyengine_version="4.2.0"
)
RUN_VERSIONS = {"country_package_version": "1.4.0", "policyengine_version": "4.1.0"}
STORED_HOUSEHOLD = {"people": {"you": {"age": {"2026": 40}}}}
BASELINE_HOUSEHOLD = {
    "people": {"you": {"age": {"2026": 40}, "net_income": {"2026": 30_000.0}}}
}
REFORM_HOUSEHOLD = {
    "people": {"you": {"age": {"2026": 40}, "net_income": {"2026": 31_250.5}}}
}
SPM_PROVENANCE = {"scenario": "baseline", "geography": "national"}
INPUT_ERRORS = [{"name": "employment_incme", "message": "is not a variable"}]


def succeeded_document(
    household: dict[str, Any], **output_changes: Any
) -> dict[str, Any]:
    """Return the household function's result document for a calculated household."""
    return {
        "status": "succeeded",
        "schema_version": 1,
        "output": {
            "household": household,
            "warnings": [],
            "spm_config": None,
            "spm_provenance": None,
            **output_changes,
        },
    }


def failed_document(**error_changes: Any) -> dict[str, Any]:
    """Return the household function's failure document for a refused calculation."""
    return {
        "status": "failed",
        "schema_version": 1,
        "error": {
            "code": "invalid_inputs",
            "message": "The household names inputs the model does not have.",
            "input_errors": INPUT_ERRORS,
            "spm_error": None,
            **error_changes,
        },
    }


def current_versions(country_id: str) -> PackageVersions:
    return CURRENT_VERSIONS


@pytest.fixture
def engine() -> Iterator[Engine]:
    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, class_=Session, expire_on_commit=False)


@pytest.fixture
def reports(sessions: sessionmaker[Session]) -> V2StoredReportService:
    return V2StoredReportService(
        StoredReportDatabaseSession(sessions), current_versions=current_versions
    )


@dataclass(frozen=True)
class StoredHouseholdReport:
    """The IDs of a stored household report and the rows it names."""

    report_id: UUID
    household_id: UUID
    policy_id: UUID
    baseline_simulation_id: UUID
    reform_simulation_id: UUID | None
    report_run_id: UUID | None
    baseline_run_id: UUID | None
    reform_run_id: UUID | None


@dataclass(frozen=True)
class RunToStore:
    """A report run to store: its status, and each simulation run's result.

    Each simulation run has the status its document records, as the
    household function writes it, or the report run's without one.
    """

    status: ReportRunStatus = ReportRunStatus.SUCCEEDED
    baseline_result: dict[str, Any] | None = None
    reform_result: dict[str, Any] | None = None
    error_message: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in {ReportRunStatus.SUCCEEDED, ReportRunStatus.FAILED}


def store_household_report(
    session: Session,
    *,
    country: str = "us",
    with_reform: bool = True,
    run: RunToStore | None = None,
) -> StoredHouseholdReport:
    """Store a household report as the simulation service and its functions do.

    Its baseline is current law and its reform a stored policy; without
    ``with_reform`` it is a report of the baseline alone. ``run`` is its one
    report run, with a run of each simulation; None stores no run.
    """
    model = TaxBenefitModel(name=f"policyengine-{country}")
    version = TaxBenefitModelVersion(
        model=model,
        version=f"reads-{uuid4().hex[:8]}",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    household = Household(
        country_id=country,
        default_year=2026,
        household_data=STORED_HOUSEHOLD,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    policy = Policy(
        country_id=country,
        tax_benefit_model=model,
        tax_benefit_model_version=version,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    session.add_all([model, version, household, policy])
    session.flush()

    def simulation(policy_id: UUID | None) -> Simulation:
        return Simulation(
            simulation_type=SimulationType.HOUSEHOLD,
            household_id=household.id,
            policy_id=policy_id,
            tax_benefit_model_version_id=version.id,
            year=2026,
        )

    baseline = simulation(None)
    reform = simulation(policy.id) if with_reform else None
    session.add_all([side for side in (baseline, reform) if side is not None])
    session.flush()
    report = Report(
        label="My household under the reform",
        description="Doubles the credit",
        country=country,
        tax_benefit_model_id=model.id,
        baseline_simulation_id=baseline.id,
        reform_simulation_id=None if reform is None else reform.id,
        household_id=household.id,
        policy_id=None if reform is None else policy.id,
        year=2026,
        inputs={},
        created_at=STORED_AT,
    )
    session.add(report)
    session.flush()
    report_run_id = baseline_run_id = reform_run_id = None
    if run is not None:
        completed_at = STORED_AT + timedelta(minutes=1) if run.finished else None

        def simulation_run(
            simulation_id: UUID, document: dict[str, Any] | None
        ) -> SimulationRun:
            recorded_status = (document or {}).get("status")
            status = SimulationStatus(
                recorded_status
                if recorded_status in {"succeeded", "failed"}
                else run.status.value
            )
            finished = status in {SimulationStatus.SUCCEEDED, SimulationStatus.FAILED}
            return SimulationRun(
                simulation_id=simulation_id,
                year=2026,
                tax_benefit_model_version_id=version.id,
                status=status,
                started_at=STORED_AT,
                completed_at=completed_at or (STORED_AT if finished else None),
                household_result=document,
                **RUN_VERSIONS,
            )

        baseline_run = simulation_run(baseline.id, run.baseline_result)
        reform_run = (
            None if reform is None else simulation_run(reform.id, run.reform_result)
        )
        session.add_all([side for side in (baseline_run, reform_run) if side])
        session.flush()
        report_run = ReportRun(
            report_id=report.id,
            baseline_simulation_run_id=baseline_run.id,
            reform_simulation_run_id=None if reform_run is None else reform_run.id,
            status=run.status,
            trigger=ReportRunTrigger.INITIAL,
            created_at=STORED_AT,
            started_at=STORED_AT,
            completed_at=completed_at,
            error_message=run.error_message,
            **RUN_VERSIONS,
        )
        session.add(report_run)
        session.flush()
        report_run_id = report_run.id
        baseline_run_id = baseline_run.id
        reform_run_id = None if reform_run is None else reform_run.id
    session.commit()
    return StoredHouseholdReport(
        report_id=report.id,
        household_id=household.id,
        policy_id=policy.id,
        baseline_simulation_id=baseline.id,
        reform_simulation_id=None if reform is None else reform.id,
        report_run_id=report_run_id,
        baseline_run_id=baseline_run_id,
        reform_run_id=reform_run_id,
    )


def succeeded_run(**changes: Any) -> RunToStore:
    values: dict[str, Any] = {
        "baseline_result": succeeded_document(BASELINE_HOUSEHOLD),
        "reform_result": succeeded_document(
            REFORM_HOUSEHOLD,
            warnings=["ignored_input"],
            spm_config={"geography_kind": "national"},
            spm_provenance=SPM_PROVENANCE,
        ),
    }
    return RunToStore(**{**values, **changes})


def test_a_succeeded_household_report_reads_both_calculated_households(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        stored = store_household_report(session, run=succeeded_run())

    report = reports.get_report(country_id="us", report_id=stored.report_id)

    assert isinstance(report, HouseholdReportRead)
    assert report.kind == "household"
    assert report.household_id == stored.household_id
    # A household report has no region or dataset.
    assert not hasattr(report, "region_code")
    assert not hasattr(report, "dataset_name")
    # A label is the requesting user's saved report's; this read names no user.
    assert (report.label, report.description, report.year) == (None, None, 2026)
    assert report.options == {}
    assert report.baseline_simulation is not None
    assert report.baseline_simulation.id == stored.baseline_simulation_id
    assert report.baseline_simulation.policy_id is None
    assert report.reform_simulation is not None
    assert report.reform_simulation.policy_id == stored.policy_id
    assert report.status == "succeeded"
    assert report.run is not None
    assert report.run.id == stored.report_run_id
    assert report.run.baseline_simulation_run_id == stored.baseline_run_id
    assert report.run.reform_simulation_run_id == stored.reform_run_id
    assert report.run.country_package_version == "1.4.0"
    assert report.current_versions == CURRENT_VERSIONS
    assert report.failure is None
    assert report.result == HouseholdReportResult(
        baseline=HouseholdCalculationOutput(
            household=BASELINE_HOUSEHOLD,
            warnings=(),
            spm_config=None,
            spm_provenance=None,
        ),
        reform=HouseholdCalculationOutput(
            household=REFORM_HOUSEHOLD,
            warnings=("ignored_input",),
            spm_config={"geography_kind": "national"},
            spm_provenance=SPM_PROVENANCE,
        ),
    )


def test_a_report_of_the_baseline_alone_has_no_reform(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        stored = store_household_report(
            session, with_reform=False, run=succeeded_run(reform_result=None)
        )

    report = reports.get_report(country_id="us", report_id=stored.report_id)

    assert isinstance(report, HouseholdReportRead)
    assert report.reform_simulation is None
    assert report.run is not None
    assert report.run.reform_simulation_run_id is None
    assert report.result is not None
    assert report.result.baseline.household == BASELINE_HOUSEHOLD
    assert report.result.reform is None


@pytest.mark.parametrize(
    "status",
    [ReportRunStatus.PENDING, ReportRunStatus.RUNNING, ReportRunStatus.FAILED],
)
def test_a_household_report_whose_newest_run_has_not_succeeded_has_no_result(
    sessions: sessionmaker[Session],
    reports: V2StoredReportService,
    status: ReportRunStatus,
) -> None:
    error_message = (
        "household_function_error" if status is ReportRunStatus.FAILED else None
    )
    with sessions() as session:
        stored = store_household_report(
            session, run=RunToStore(status=status, error_message=error_message)
        )

    report = reports.get_report(country_id="us", report_id=stored.report_id)

    assert isinstance(report, HouseholdReportRead)
    assert report.status == status.value
    assert report.run is not None
    assert report.run.error_message == error_message
    assert report.result is None
    # Neither simulation run holds a failure document here.
    assert report.failure == (
        HouseholdReportFailure(baseline=None, reform=None)
        if status is ReportRunStatus.FAILED
        else None
    )


def test_a_failed_household_report_answers_each_sides_failure(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    # Both sides are always calculated: the baseline succeeded, the reform's
    # calculation was refused, so the report run failed.
    with sessions() as session:
        stored = store_household_report(
            session,
            run=RunToStore(
                status=ReportRunStatus.FAILED,
                error_message="household_calculation_failed: invalid_inputs",
                baseline_result=succeeded_document(BASELINE_HOUSEHOLD),
                reform_result=failed_document(),
            ),
        )

    report = reports.get_report(country_id="us", report_id=stored.report_id)

    assert isinstance(report, HouseholdReportRead)
    assert report.result is None
    assert report.failure == HouseholdReportFailure(
        baseline=None,
        reform=HouseholdReportSideFailure(
            code="invalid_inputs",
            message="The household names inputs the model does not have.",
            input_errors=tuple(INPUT_ERRORS),
            spm_error=None,
        ),
    )


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({"status": "failed", "schema_version": 1}, id="no-error"),
        pytest.param({**failed_document(), "schema_version": 2}, id="version-2"),
        pytest.param({"unexpected": True}, id="another-document"),
    ],
)
def test_a_failure_document_that_cannot_be_read_names_no_failure(
    sessions: sessionmaker[Session],
    reports: V2StoredReportService,
    document: dict[str, Any],
) -> None:
    # The run's error message still says why it failed.
    with sessions() as session:
        stored = store_household_report(
            session,
            with_reform=False,
            run=RunToStore(
                status=ReportRunStatus.FAILED,
                error_message="household_calculation_failed",
                baseline_result=document,
            ),
        )

    report = reports.get_report(country_id="us", report_id=stored.report_id)

    assert isinstance(report, HouseholdReportRead)
    assert report.failure == HouseholdReportFailure(baseline=None, reform=None)


def test_a_household_report_with_no_run_answers_its_definition(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        stored = store_household_report(session, run=None)

    report = reports.get_report(country_id="us", report_id=stored.report_id)

    assert isinstance(report, HouseholdReportRead)
    assert (report.status, report.run, report.result) == ("not_run", None, None)
    assert report.failure is None


@pytest.mark.parametrize(
    ("side", "document"),
    [
        pytest.param("baseline_result", None, id="no-document"),
        pytest.param(
            "reform_result",
            {"status": "failed", "schema_version": 1, "error": {"code": "x"}},
            id="failure-document",
        ),
        pytest.param(
            "baseline_result",
            {**succeeded_document(BASELINE_HOUSEHOLD), "schema_version": 2},
            id="another-schema-version",
        ),
        pytest.param(
            "reform_result",
            {"status": "succeeded", "schema_version": 1},
            id="no-output",
        ),
    ],
)
def test_a_succeeded_run_whose_calculated_household_cannot_be_read_is_unreadable(
    sessions: sessionmaker[Session],
    reports: V2StoredReportService,
    side: str,
    document: dict[str, Any] | None,
) -> None:
    with sessions() as session:
        stored = store_household_report(session, run=succeeded_run(**{side: document}))

    with pytest.raises(HouseholdResultUnreadableError):
        reports.get_report(country_id="us", report_id=stored.report_id)


def test_a_household_report_of_another_country_is_not_found(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        stored = store_household_report(session, country="uk", run=succeeded_run())

    with pytest.raises(StoredReportNotFoundError):
        reports.get_report(country_id="us", report_id=stored.report_id)


def store_economy_report(session: Session) -> UUID:
    """Store an economy report with no run, in the US."""
    model = TaxBenefitModel(name="policyengine-us-economy")
    session.add(model)
    session.flush()
    report = Report(
        label="Economy",
        country="us",
        tax_benefit_model_id=model.id,
        year=2026,
        inputs={"include_cliffs": False},
        created_at=STORED_AT,
    )
    session.add(report)
    session.commit()
    return report.id


def test_a_list_names_household_reports_beside_economy_reports_without_results(
    sessions: sessionmaker[Session], reports: V2StoredReportService
) -> None:
    with sessions() as session:
        household = store_household_report(session, run=succeeded_run())
        economy_report_id = store_economy_report(session)
        other_country = store_household_report(session, country="uk")

    listed = reports.list_reports(
        country_id="us",
        report_ids=[
            household.report_id,
            other_country.report_id,
            economy_report_id,
            household.report_id,
        ],
    )

    assert [report.id for report in listed] == [
        household.report_id,
        economy_report_id,
    ]
    household_summary, economy_summary = listed
    assert type(household_summary) is HouseholdReportSummaryRead
    assert household_summary.household_id == household.household_id
    assert household_summary.status == "succeeded"
    assert not hasattr(household_summary, "result")
    assert type(economy_summary) is ReportSummaryRead


@dataclass
class StoringHouseholdReportService:
    """The simulation service, storing a pending household report for each one sent.

    With ``answer_unstored``, it answers with a report ID it stored nothing
    for. An economy report must not reach it.
    """

    sessions: sessionmaker[Session]
    answer_unstored: bool = False
    sent: list[HouseholdReportCreationInput] | None = None

    def submit_household_report(
        self, report: HouseholdReportCreationInput
    ) -> SubmittedReport:
        self.sent = [*(self.sent or []), report]
        if self.answer_unstored:
            return SubmittedReport(report_id=uuid4(), report_run_id=uuid4())
        with self.sessions() as session:
            stored = store_household_report(
                session, run=RunToStore(status=ReportRunStatus.PENDING)
            )
        assert stored.report_run_id is not None
        return SubmittedReport(
            report_id=stored.report_id, report_run_id=stored.report_run_id
        )

    def submit_report(self, report: object) -> SubmittedReport:
        msg = "a household report must not be sent as an economy report"
        raise AssertionError(msg)


def household_report_input() -> HouseholdReportCreationInput:
    return HouseholdReportCreationInput.model_validate(
        {
            "country_id": "us",
            "kind": "household",
            "label": "My household under the reform",
            "household_id": str(uuid4()),
            "baseline": {},
            "reform": None,
        }
    )


def test_a_household_report_is_sent_as_one_and_read_back_from_the_tables(
    sessions: sessionmaker[Session],
) -> None:
    simulation_service = StoringHouseholdReportService(sessions)
    reports = V2StoredReportService(
        StoredReportDatabaseSession(sessions),
        current_versions=current_versions,
        submissions=simulation_service,
    )
    report_input = household_report_input()

    created = reports.create_report(report_input)

    assert simulation_service.sent == [report_input]
    assert isinstance(created, HouseholdReportRead)
    assert (created.status, created.result, created.failure) == (
        "pending",
        None,
        None,
    )


def test_a_created_household_report_that_cannot_be_read_back_is_named(
    sessions: sessionmaker[Session],
) -> None:
    reports = V2StoredReportService(
        StoredReportDatabaseSession(sessions),
        current_versions=current_versions,
        submissions=StoringHouseholdReportService(sessions, answer_unstored=True),
    )

    with pytest.raises(CreatedReportUnreadableError) as unreadable:
        reports.create_report(household_report_input())

    assert unreadable.value.country_id == "us"
    assert isinstance(unreadable.value.__cause__, StoredReportNotFoundError)
