"""Pin report-run creation's validation, key-less insert and conflict paths."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Report,
    ReportRun,
    ReportRunStatus,
    ReportRunTrigger,
    TaxBenefitModel,
)
from policyengine_api.data.v2.report_runs import (
    ReportNotFoundError,
    ReportRunPackageVersions,
    create_report_run,
)


@pytest.fixture
def engine():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


def _create_report(session: Session) -> Report:
    report = Report(
        label="Distributional report",
        country="us",
        tax_benefit_model=TaxBenefitModel(name=f"model-{uuid4()}"),
        inputs={},
    )
    session.add(report)
    session.flush()
    return report


def test_unknown_report_is_rejected_before_any_validation(engine) -> None:
    with (
        Session(engine) as session,
        pytest.raises(ReportNotFoundError, match="does not exist"),
    ):
        create_report_run(
            session,
            report_id=uuid4(),
            versions=ReportRunPackageVersions(
                country_package_version="",
                policyengine_version="",
            ),
            trigger=ReportRunTrigger.MANUAL,
        )


def test_manual_run_without_a_key_is_rejected_before_version_checks(engine) -> None:
    with Session(engine) as session:
        report = _create_report(session)

        with pytest.raises(
            ValueError, match=r"^manual report reruns require an idempotency key$"
        ):
            create_report_run(
                session,
                report_id=report.id,
                versions=ReportRunPackageVersions(
                    country_package_version="",
                    policyengine_version="",
                ),
                trigger=ReportRunTrigger.MANUAL,
            )


@pytest.mark.parametrize(
    ("country_package_version", "policyengine_version"),
    [("", "4.5.6"), ("1.2.3", "")],
)
def test_empty_package_versions_are_rejected(
    engine,
    country_package_version: str,
    policyengine_version: str,
) -> None:
    with Session(engine) as session:
        report = _create_report(session)

        with pytest.raises(
            ValueError, match=r"^report run package versions must be non-empty$"
        ):
            create_report_run(
                session,
                report_id=report.id,
                versions=ReportRunPackageVersions(
                    country_package_version=country_package_version,
                    policyengine_version=policyengine_version,
                ),
                trigger=ReportRunTrigger.SYSTEM,
            )


def test_run_without_a_key_is_inserted_without_a_savepoint(engine) -> None:
    with Session(engine) as session:
        report = _create_report(session)

        run = create_report_run(
            session,
            report_id=report.id,
            versions=ReportRunPackageVersions(
                country_package_version="1.2.3",
                policyengine_version="4.5.6",
            ),
            trigger=ReportRunTrigger.INITIAL,
        )

        stored = session.exec(select(ReportRun)).one()
        assert stored is run
        assert run.report_id == report.id
        assert run.country_package_version == "1.2.3"
        assert run.policyengine_version == "4.5.6"
        assert run.trigger is ReportRunTrigger.INITIAL
        assert run.idempotency_key is None
        assert run.status is ReportRunStatus.PENDING


def test_conflict_without_a_matching_keyed_run_reraises(
    engine,
    monkeypatch,
) -> None:
    conflict = IntegrityError("insert", {}, Exception("unrelated constraint"))

    @contextmanager
    def failing_savepoint():
        raise conflict
        yield

    with Session(engine) as session:
        report = _create_report(session)
        monkeypatch.setattr(session, "begin_nested", failing_savepoint)

        with pytest.raises(IntegrityError) as raised:
            create_report_run(
                session,
                report_id=report.id,
                versions=ReportRunPackageVersions(
                    country_package_version="1.2.3",
                    policyengine_version="4.5.6",
                ),
                trigger=ReportRunTrigger.MANUAL,
                idempotency_key=uuid4(),
            )

    assert raised.value is conflict
