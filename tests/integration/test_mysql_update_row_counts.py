"""Real MySQL checks of the row counts the v1 engine reports for ORM UPDATEs.

SQLAlchemy raises StaleDataError when an ORM UPDATE reports fewer rows than it
expected. MySQL counts only the rows whose values changed unless the connection
sets the CLIENT.FOUND_ROWS flag, so an UPDATE that writes values the row already
holds reports 0 rows without it.

Use the local, Alembic-migrated MySQL database that ``ALEMBIC_DATABASE_URL``
names. API v1's own engine is built as in production, with a stand-in for the
Cloud SQL connector that opens pymysql connections to that server and passes on
the connection arguments the engine gives it, as the real connector does
(``v1_cloud_sql_sessions``). Only the row each test creates is removed during
cleanup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm.exc import StaleDataError

from policyengine_api.data import orm
from policyengine_api.data.v1_models import ReportOutput
from tests.fixtures.database_sessions import v1_cloud_sql_sessions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import CursorResult
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql.dml import Update


@pytest.fixture
def v1_engine_sessions(
    monkeypatch: pytest.MonkeyPatch, disposable_v1_database_url: str
) -> Iterator[sessionmaker[Session]]:
    """Yield API v1's Session factory, on the engine orm._build_remote_engine builds."""
    with v1_cloud_sql_sessions(monkeypatch, disposable_v1_database_url) as sessions:
        yield sessions


@pytest.fixture
def sessions_without_found_rows(
    monkeypatch: pytest.MonkeyPatch, disposable_v1_database_url: str
) -> Iterator[sessionmaker[Session]]:
    """Yield Session factories on the v1 engine, its connections with no client flags.

    Only the CLIENT.FOUND_ROWS flag the engine passes to each connection
    differs from API v1's engine: it is replaced by none.
    """
    monkeypatch.setattr(orm, "MYSQL_CLIENT_FOUND_ROWS_FLAG", 0)
    with v1_cloud_sql_sessions(monkeypatch, disposable_v1_database_url) as sessions:
        yield sessions


def _create_pending_report_output(sessions: sessionmaker[Session]) -> int:
    with sessions.begin() as session:
        report_output = ReportOutput(
            country_id="us",
            simulation_1_id=0,
            api_version="found-rows",
            status="pending",
        )
        session.add(report_output)
        session.flush()
        return report_output.id


def _delete_report_output(
    sessions: sessionmaker[Session], report_output_id: int
) -> None:
    with sessions.begin() as session:
        session.execute(delete(ReportOutput).where(ReportOutput.id == report_output_id))


def _set_complete(report_output_id: int) -> Update:
    """Return an ORM UPDATE that sets the row complete behind any loaded object."""
    return (
        update(ReportOutput)
        .where(ReportOutput.id == report_output_id)
        .values(status="complete")
        .execution_options(synchronize_session=False)
    )


def _row_count(session: Session, statement: Update) -> int:
    """Run an UPDATE in the Session and return the row count MySQL reports."""
    result = cast("CursorResult[Any]", session.execute(statement))
    return result.rowcount


def _rows_reported_for_unchanged_update(
    sessions: sessionmaker[Session], report_output_id: int
) -> int:
    """Return the row count of an ORM UPDATE that writes the values the row holds.

    The first UPDATE sets the pending row complete and the second sets it
    complete again. Closing the Session rolls both back.
    """
    with sessions() as session:
        assert _row_count(session, _set_complete(report_output_id)) == 1
        return _row_count(session, _set_complete(report_output_id))


def _complete_report_output_already_completed_by_statement(
    sessions: sessionmaker[Session], report_output_id: int
) -> None:
    """Have the ORM write a status that an UPDATE set earlier in the same transaction.

    The ORM loads the row while it is pending, an ORM UPDATE statement then sets
    it complete without changing the loaded object, and the object sets complete
    again and flushes. MySQL finds the row but changes nothing.
    """
    with sessions.begin() as session:
        report_output = session.scalar(
            select(ReportOutput)
            .where(ReportOutput.id == report_output_id)
            .with_for_update()
        )
        assert report_output is not None
        assert report_output.status == "pending"
        session.execute(_set_complete(report_output_id))
        report_output.status = "complete"
        session.flush()


def test_orm_update_to_unchanged_values_raises_without_found_rows(
    sessions_without_found_rows: sessionmaker[Session],
) -> None:
    report_output_id = _create_pending_report_output(sessions_without_found_rows)
    try:
        assert (
            _rows_reported_for_unchanged_update(
                sessions_without_found_rows, report_output_id
            )
            == 0
        )
        with pytest.raises(StaleDataError, match="0 were matched"):
            _complete_report_output_already_completed_by_statement(
                sessions_without_found_rows, report_output_id
            )
    finally:
        _delete_report_output(sessions_without_found_rows, report_output_id)


def test_v1_engine_orm_update_to_unchanged_values_succeeds(
    v1_engine_sessions: sessionmaker[Session],
) -> None:
    report_output_id = _create_pending_report_output(v1_engine_sessions)
    try:
        assert (
            _rows_reported_for_unchanged_update(v1_engine_sessions, report_output_id)
            == 1
        )
        _complete_report_output_already_completed_by_statement(
            v1_engine_sessions, report_output_id
        )

        with v1_engine_sessions() as session:
            report_output = session.get(ReportOutput, report_output_id)
            assert report_output is not None
            assert report_output.status == "complete"
    finally:
        _delete_report_output(v1_engine_sessions, report_output_id)
