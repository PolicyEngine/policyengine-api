"""Pin report-run creation's validation, key-less insert and conflict paths."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    Report,
    ReportRun,
    ReportRunStatus,
    TaxBenefitModel,
)
from policyengine_api.data.v2.report_runs import (
    ReportNotFoundError,
    ReportRunInputs,
    ReportRunPackageVersions,
    ReportRunSimulationRuns,
    create_report_run,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker

# The simulation runs each report run compares. SQLite doesn't enforce foreign
# keys, so these tests store no simulation run rows for them.
SIMULATION_RUNS = ReportRunSimulationRuns(
    baseline_simulation_run_id=UUID(int=101), reform_simulation_run_id=UUID(int=102)
)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    with sqlite_v2_sessions() as session_factory:
        yield session_factory


def _create_report(session: Session) -> Report:
    model = TaxBenefitModel(name=f"model-{uuid4()}")
    session.add(model)
    session.flush()
    report = Report(
        country="us",
        tax_benefit_model_id=model.id,
        inputs={},
    )
    session.add(report)
    session.flush()
    return report


def test_unknown_report_is_rejected_before_any_validation(sessions) -> None:
    with (
        sessions(expire_on_commit=True) as session,
        pytest.raises(ReportNotFoundError, match="does not exist"),
    ):
        create_report_run(
            session,
            report_id=uuid4(),
            inputs=ReportRunInputs(
                versions=ReportRunPackageVersions(
                    country_package_version="",
                    policyengine_version="",
                ),
                simulation_runs=SIMULATION_RUNS,
            ),
        )


@pytest.mark.parametrize(
    ("country_package_version", "policyengine_version"),
    [("", "4.5.6"), ("1.2.3", "")],
)
def test_empty_package_versions_are_rejected(
    sessions,
    country_package_version: str,
    policyengine_version: str,
) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)

        with pytest.raises(
            ValueError, match=r"^report run package versions must be non-empty$"
        ):
            create_report_run(
                session,
                report_id=report.id,
                inputs=ReportRunInputs(
                    versions=ReportRunPackageVersions(
                        country_package_version=country_package_version,
                        policyengine_version=policyengine_version,
                    ),
                    simulation_runs=SIMULATION_RUNS,
                ),
            )


def test_run_without_a_key_is_inserted_without_a_savepoint(sessions) -> None:
    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)

        run = create_report_run(
            session,
            report_id=report.id,
            inputs=ReportRunInputs(
                versions=ReportRunPackageVersions(
                    country_package_version="1.2.3",
                    policyengine_version="4.5.6",
                ),
                simulation_runs=SIMULATION_RUNS,
            ),
        )

        stored = session.exec(select(ReportRun)).one()
        assert stored is run
        assert run.report_id == report.id
        assert run.country_package_version == "1.2.3"
        assert run.policyengine_version == "4.5.6"
        assert run.idempotency_key is None
        assert run.status is ReportRunStatus.PENDING
        assert run.baseline_simulation_run_id == UUID(int=101)
        assert run.reform_simulation_run_id == UUID(int=102)


def test_conflict_without_a_matching_keyed_run_reraises(
    sessions,
    monkeypatch,
) -> None:
    conflict = IntegrityError("insert", {}, Exception("unrelated constraint"))

    @contextmanager
    def failing_savepoint():
        raise conflict
        yield

    with sessions(expire_on_commit=True) as session:
        report = _create_report(session)
        monkeypatch.setattr(session, "begin_nested", failing_savepoint)

        with pytest.raises(IntegrityError) as raised:
            create_report_run(
                session,
                report_id=report.id,
                inputs=ReportRunInputs(
                    versions=ReportRunPackageVersions(
                        country_package_version="1.2.3",
                        policyengine_version="4.5.6",
                    ),
                    simulation_runs=SIMULATION_RUNS,
                ),
                idempotency_key=uuid4(),
            )

    assert raised.value is conflict
