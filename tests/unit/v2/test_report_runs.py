"""Report definition, rerun, idempotency, worker, and selector tests."""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    AggregateOutput,
    AggregateType,
    Dataset,
    Report,
    ReportRun,
    ReportRunStatus,
    Simulation,
    SimulationType,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.report_runs import (
    ReportRunInputs,
    ReportRunPackageVersions,
    ReportRunSimulationRuns,
    ReportRunStateError,
    ReportTypeImmutableError,
    begin_report_run,
    complete_report_run,
    create_report_run,
    fail_report_run,
    select_current_report_run,
    set_report_type,
)
from tests.fixtures.database_sessions import (
    sqlite_v2_file_sessions,
    sqlite_v2_sessions,
)
from tests.unit.v2.v2_schema_reading import model_columns

DEPLOYED_COUNTRY_VERSIONS = {"us": "1.2.3"}
DEPLOYED_POLICYENGINE_VERSION = "4.5.6"
NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
# The simulation runs each report run compares. SQLite doesn't enforce foreign
# keys, so these tests store no simulation run rows for them.
SIMULATION_RUNS = ReportRunSimulationRuns(
    baseline_simulation_run_id=UUID(int=101), reform_simulation_run_id=UUID(int=102)
)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    with sqlite_v2_sessions() as session_factory:
        yield session_factory


def _create_report(session: Session, *, report_type: str | None = None) -> Report:
    model = TaxBenefitModel(name=f"model-{uuid4()}")
    session.add(model)
    session.flush()
    report = Report(
        country="us",
        type=report_type,
        tax_benefit_model_id=model.id,
        inputs={"reform": {"gov.example": 1}},
    )
    session.add(report)
    session.flush()
    return report


def _create_run(
    session: Session,
    report: Report,
    *,
    key: UUID | None = None,
    country_version: str = "1.2.3",
    policyengine_version: str = DEPLOYED_POLICYENGINE_VERSION,
) -> ReportRun:
    return create_report_run(
        session,
        report_id=report.id,
        inputs=ReportRunInputs(
            versions=ReportRunPackageVersions(
                country_package_version=country_version,
                policyengine_version=policyengine_version,
            ),
            simulation_runs=SIMULATION_RUNS,
        ),
        idempotency_key=key if key is not None else uuid4(),
    )


def _create_forced_run(session: Session, report: Report) -> ReportRun:
    """Store a forced re-run on the deployed versions: an extra run nothing joins.

    Only a forced re-run may run beside another run on the same versions that
    hasn't failed; ``create_report_run`` creates unforced runs only.
    """
    run = ReportRun(
        report_id=report.id,
        baseline_simulation_run_id=SIMULATION_RUNS.baseline_simulation_run_id,
        reform_simulation_run_id=SIMULATION_RUNS.reform_simulation_run_id,
        country_package_version="1.2.3",
        policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
        idempotency_key=uuid4(),
        forced=True,
    )
    session.add(run)
    session.flush()
    return run


def test_untyped_and_typed_report_definitions_store_no_execution_versions(
    sessions,
) -> None:
    with sessions(expire_on_commit=True) as session:
        untyped = _create_report(session)
        typed = _create_report(session, report_type="marginal_tax_rate")

        assert untyped.type is None
        assert typed.type == "marginal_tax_rate"
        assert "country_package_version" not in model_columns(Report)
        assert "policyengine_version" not in model_columns(Report)


def test_report_type_can_change_before_first_run_but_not_after(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        set_report_type(
            session,
            report_id=report.id,
            report_type="marginal_tax_rate",
        )
        _create_run(session, report)

        unchanged = set_report_type(
            session,
            report_id=report.id,
            report_type="marginal_tax_rate",
        )
        assert unchanged.id == report.id
        with pytest.raises(ReportTypeImmutableError):
            set_report_type(
                session,
                report_id=report.id,
                report_type="economy_comparison",
            )


def test_new_keys_create_a_same_version_run_once_the_last_one_failed(
    sessions,
) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        first = _create_run(session, report)
        # A report has one unfailed, unforced run per version set.
        with pytest.raises(IntegrityError):
            _create_run(session, report)
        fail_report_run(
            session, report_run_id=first.id, error_message="failed", completed_at=NOW
        )
        second = _create_run(session, report)

        assert first.id != second.id
        assert first.country_package_version == second.country_package_version
        assert first.policyengine_version == second.policyengine_version
        assert len(session.exec(select(ReportRun)).all()) == 2


def test_idempotency_key_round_trips_as_a_python_uuid(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        request_key = uuid4()
        run = _create_run(session, report, key=request_key)
        session.flush()
        session.expire(run)

        assert run.idempotency_key == request_key
        assert isinstance(run.idempotency_key, UUID)


def test_transport_retry_returns_the_existing_report_scoped_run(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        request_key = uuid4()
        first = _create_run(session, report, key=request_key)
        retried = _create_run(session, report, key=request_key)

        assert retried.id == first.id
        assert len(session.exec(select(ReportRun)).all()) == 1


@pytest.fixture
def file_sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    # Each transaction begins with BEGIN IMMEDIATE, which gives this explicit
    # SQLite-only test fixture the same serialization point that SELECT FOR
    # UPDATE provides in Postgres.
    with sqlite_v2_file_sessions(tmp_path / "report-rerun-concurrency.db") as sessions:
        yield sessions


def test_concurrent_idempotent_requests_resolve_to_one_run(
    file_sessions: sessionmaker[Session],
) -> None:
    with file_sessions(expire_on_commit=True) as session:
        report_id = _create_report(session).id
        session.commit()

    barrier = threading.Barrier(2)
    request_key = uuid4()

    def request_rerun() -> UUID:
        with file_sessions(expire_on_commit=True) as session:
            barrier.wait()
            run = create_report_run(
                session,
                report_id=report_id,
                inputs=ReportRunInputs(
                    versions=ReportRunPackageVersions(
                        country_package_version="1.2.3",
                        policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
                    ),
                    simulation_runs=SIMULATION_RUNS,
                ),
                idempotency_key=request_key,
            )
            run_id = run.id
            session.commit()
            return run_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        run_ids = set(executor.map(lambda _: request_rerun(), range(2)))

    with file_sessions(expire_on_commit=True) as session:
        assert len(run_ids) == 1
        assert len(session.exec(select(ReportRun)).all()) == 1


def test_worker_retry_resumes_the_same_run_and_terminal_runs_stay_terminal(
    sessions,
) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        run = _create_run(session, report)
        started = begin_report_run(session, report_run_id=run.id, started_at=NOW)
        resumed = begin_report_run(session, report_run_id=run.id)

        assert resumed.id == run.id
        assert resumed.status is ReportRunStatus.RUNNING
        assert resumed.started_at == started.started_at
        assert len(session.exec(select(ReportRun)).all()) == 1

        complete_report_run(session, report_run_id=run.id, completed_at=NOW)
        with pytest.raises(ReportRunStateError):
            begin_report_run(session, report_run_id=run.id)


def test_outputs_from_repeated_runs_are_preserved(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        version = TaxBenefitModelVersion(
            model_id=report.tax_benefit_model_id,
            version="1.2.3",
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        session.add(version)
        session.flush()
        dataset = Dataset(
            name="dataset",
            storage_path="datasets/test.h5",
            year=2026,
            tax_benefit_model_version_id=version.id,
        )
        session.add(dataset)
        session.flush()
        simulation = Simulation(
            simulation_type=SimulationType.ECONOMY,
            dataset_id=dataset.id,
            tax_benefit_model_version_id=version.id,
        )
        session.add(simulation)
        session.flush()
        first = _create_run(session, report)
        second = _create_forced_run(session, report)
        session.add_all(
            [
                AggregateOutput(
                    report_run=first,
                    simulation_id=simulation.id,
                    variable="household_net_income",
                    aggregate_type=AggregateType.SUM,
                    result=1.0,
                ),
                AggregateOutput(
                    report_run=second,
                    simulation_id=simulation.id,
                    variable="household_net_income",
                    aggregate_type=AggregateType.SUM,
                    result=2.0,
                ),
            ]
        )
        session.flush()

        outputs = session.exec(
            select(AggregateOutput).order_by(AggregateOutput.result)
        ).all()
        assert [output.result for output in outputs] == [1.0, 2.0]
        assert outputs[0].report_run_id != outputs[1].report_run_id


def test_selector_uses_versions_success_completion_time_and_stable_id(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        # Runs 1 and 4 share run 2's versions, so each is a forced re-run.
        candidates = [
            ReportRun(
                id=UUID(int=1),
                report=report,
                baseline_simulation_run_id=UUID(int=101),
                country_package_version="1.2.3",
                policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
                status=ReportRunStatus.SUCCEEDED,
                completed_at=NOW,
                forced=True,
            ),
            ReportRun(
                id=UUID(int=2),
                report=report,
                baseline_simulation_run_id=UUID(int=101),
                country_package_version="1.2.3",
                policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
                status=ReportRunStatus.SUCCEEDED,
                completed_at=NOW,
            ),
            ReportRun(
                id=UUID(int=3),
                report=report,
                baseline_simulation_run_id=UUID(int=101),
                country_package_version="9.9.9",
                policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
                status=ReportRunStatus.SUCCEEDED,
                completed_at=NOW + timedelta(days=1),
            ),
            ReportRun(
                id=UUID(int=4),
                report=report,
                baseline_simulation_run_id=UUID(int=101),
                country_package_version="1.2.3",
                policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
                status=ReportRunStatus.RUNNING,
                forced=True,
            ),
        ]
        session.add_all(candidates)
        session.flush()

        current = select_current_report_run(
            session,
            report_id=report.id,
            country_package_versions=DEPLOYED_COUNTRY_VERSIONS,
            policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
        )

        assert current is not None
        assert current.id == UUID(int=2)


def test_pending_and_failed_reruns_do_not_displace_success(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        successful = _create_run(session, report)
        complete_report_run(session, report_run_id=successful.id, completed_at=NOW)
        pending = _create_forced_run(session, report)
        failed = _create_forced_run(session, report)
        fail_report_run(
            session,
            report_run_id=failed.id,
            error_message="transient failure",
            completed_at=NOW + timedelta(hours=1),
        )

        current = select_current_report_run(
            session,
            report_id=report.id,
            country_package_versions=DEPLOYED_COUNTRY_VERSIONS,
            policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
        )

        assert pending.status is ReportRunStatus.PENDING
        assert current is not None
        assert current.id == successful.id


def test_new_successful_rerun_becomes_current_without_cache_state(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        first = _create_run(session, report)
        complete_report_run(session, report_run_id=first.id, completed_at=NOW)
        rerun = _create_forced_run(session, report)
        complete_report_run(
            session,
            report_run_id=rerun.id,
            completed_at=NOW + timedelta(minutes=1),
        )

        # No Redis/cache collaborator participates in durable selection; a
        # flush or expiry therefore has no state to invalidate here.
        current = select_current_report_run(
            session,
            report_id=report.id,
            country_package_versions=DEPLOYED_COUNTRY_VERSIONS,
            policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
        )

        assert current is not None
        assert current.id == rerun.id
        assert len(session.exec(select(ReportRun)).all()) == 2


def test_selector_returns_none_without_a_matching_success(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        mismatched = _create_run(
            session,
            report,
            country_version="0.0.1",
        )
        complete_report_run(session, report_run_id=mismatched.id, completed_at=NOW)

        assert (
            select_current_report_run(
                session,
                report_id=report.id,
                country_package_versions=DEPLOYED_COUNTRY_VERSIONS,
                policyengine_version=DEPLOYED_POLICYENGINE_VERSION,
            )
            is None
        )
