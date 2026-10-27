"""Real MySQL checks of the row counts the v1 engine reports for ORM UPDATEs.

SQLAlchemy raises StaleDataError when an ORM UPDATE reports fewer rows than it
expected. MySQL counts only the rows whose values changed unless the connection
sets the CLIENT.FOUND_ROWS flag, so an UPDATE that writes values the row already
holds reports 0 rows without it.

Use the local, Alembic-migrated target required by test_mysql_policy_dual_write.
The Cloud SQL connector is replaced by one that opens pymysql connections to
that server, passing on the connection arguments the engine gives it as the
real connector does. Only the row each test creates is removed during cleanup.
"""

from __future__ import annotations

import pymysql
import pytest
from sqlalchemy import Engine, create_engine, delete, select, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.pool import NullPool

from policyengine_api.data import orm
from policyengine_api.data.v1_models import ReportOutput
from tests.integration.test_mysql_policy_dual_write import _mysql_url

MYSQL_DEFAULT_PORT = 3306


class LocalMySqlConnector:
    """Stands in for the Cloud SQL connector, connecting to the local test server.

    The real connector's pymysql path passes every argument other than the
    instance name and driver on to pymysql, so this one does the same.
    """

    def __init__(self, database_url: URL, **connector_options):
        self.database_url = database_url
        self.connector_options = connector_options

    def connect(self, *, instance_connection_string, driver, **driver_arguments):
        assert driver == "pymysql"
        return pymysql.connect(
            host=self.database_url.host,
            port=self.database_url.port or MYSQL_DEFAULT_PORT,
            **driver_arguments,
        )

    def close(self):
        pass


@pytest.fixture
def mysql_database_url() -> URL:
    return make_url(_mysql_url())


@pytest.fixture
def v1_remote_engine(monkeypatch, mysql_database_url):
    """Yield the engine orm._build_remote_engine builds, connected to local MySQL."""
    monkeypatch.setattr(orm, "_cloud_sql_state", orm._CloudSqlState())
    monkeypatch.setattr(
        orm,
        "Connector",
        lambda **connector_options: LocalMySqlConnector(
            mysql_database_url, **connector_options
        ),
    )
    monkeypatch.setenv("POLICYENGINE_DB_INSTANCE_CONNECTION_NAME", "local:test:mysql")
    monkeypatch.setenv("POLICYENGINE_DB_USER", mysql_database_url.username)
    monkeypatch.setenv("POLICYENGINE_DB_NAME", mysql_database_url.database)
    monkeypatch.setenv("POLICYENGINE_DB_PASSWORD", mysql_database_url.password)
    engine = orm._build_remote_engine()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def engine_without_found_rows(mysql_database_url):
    """Yield an engine whose creator opens pymysql connections with no client flags."""

    def connect_without_found_rows():
        return pymysql.connect(
            host=mysql_database_url.host,
            port=mysql_database_url.port or MYSQL_DEFAULT_PORT,
            user=mysql_database_url.username,
            password=mysql_database_url.password,
            database=mysql_database_url.database,
        )

    engine = create_engine(
        "mysql+pymysql://",
        creator=connect_without_found_rows,
        poolclass=NullPool,
    )
    try:
        yield engine
    finally:
        engine.dispose()


def _create_pending_report_output(engine: Engine) -> int:
    with orm.build_session_factory(engine).begin() as session:
        report_output = ReportOutput(
            country_id="us",
            simulation_1_id=0,
            api_version="found-rows",
            status="pending",
        )
        session.add(report_output)
        session.flush()
        return report_output.id


def _delete_report_output(engine: Engine, report_output_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(ReportOutput).where(ReportOutput.id == report_output_id)
        )


def _complete_report_output_already_completed_by_sql(
    engine: Engine, report_output_id: int
) -> None:
    """Have the ORM write a status that SQL set earlier in the same transaction.

    The ORM loads the row while it is pending, a Core UPDATE then sets it
    complete without the ORM seeing it, and the ORM sets complete again and
    flushes. MySQL finds the row but changes nothing.
    """
    with orm.build_session_factory(engine).begin() as session:
        report_output = session.scalar(
            select(ReportOutput)
            .where(ReportOutput.id == report_output_id)
            .with_for_update()
        )
        assert report_output is not None
        assert report_output.status == "pending"
        session.connection().execute(
            update(ReportOutput.__table__)
            .where(ReportOutput.__table__.c.id == report_output_id)
            .values(status="complete")
        )
        report_output.status = "complete"
        session.flush()


def test_orm_update_to_unchanged_values_raises_without_found_rows(
    engine_without_found_rows,
):
    report_output_id = _create_pending_report_output(engine_without_found_rows)
    try:
        with pytest.raises(StaleDataError, match="0 were matched"):
            _complete_report_output_already_completed_by_sql(
                engine_without_found_rows, report_output_id
            )
    finally:
        _delete_report_output(engine_without_found_rows, report_output_id)


def test_v1_engine_orm_update_to_unchanged_values_succeeds(v1_remote_engine):
    report_output_id = _create_pending_report_output(v1_remote_engine)
    try:
        _complete_report_output_already_completed_by_sql(
            v1_remote_engine, report_output_id
        )

        with orm.build_session_factory(v1_remote_engine)() as session:
            report_output = session.get(ReportOutput, report_output_id)
            assert report_output is not None
            assert report_output.status == "complete"
    finally:
        _delete_report_output(v1_remote_engine, report_output_id)
