"""Run the simulation tables' writes as the roles that do them in production.

The simulation API creates simulations, reports, their runs and household
jobs; its Modal workers write their runs' status and results; the Public API
reads them. Each role holds only its declared privileges
(``policyengine_api/data/v2/privileges.py``), so a statement outside them
fails here as it would in staging and production.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import NullPool

from policyengine_api.constants import REPO
from tests.integration.simulation_rows import RUN_VERSIONS, insert_row, refused

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection


@pytest.fixture
def connection(disposable_v2_database_url, managed_v2_roles) -> Iterator[Connection]:
    """Yield a connection at head whose writes are rolled back after the test.

    It connects as the disposable database's superuser; ``_act_as`` switches it
    to one managed role for the rest of the transaction.
    """
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    try:
        with engine.connect() as database_connection:
            transaction = database_connection.begin()
            try:
                yield database_connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def _act_as(connection: Connection, role: str) -> None:
    quoted_role = connection.dialect.identifier_preparer.quote(role)
    connection.execute(text(f"SET LOCAL ROLE {quoted_role}"))


def _refused(connection: Connection, statement: str, **values: object) -> None:
    """Expect a permission error from ``statement``."""
    with refused(connection, ProgrammingError, match="permission denied"):
        connection.execute(text(statement), values)


def _create_simulation_rows(connection: Connection) -> dict[str, object]:
    """Create what the simulation API creates for one economy report run."""
    ids = {
        name: uuid4()
        for name in ("simulation", "run", "report", "report_run", "household_job")
    }
    insert_row(
        connection,
        "simulations",
        id=ids["simulation"],
        simulation_type="economy",
        dataset_id=uuid4(),
        tax_benefit_model_version_id=uuid4(),
        year=2026,
    )
    insert_row(
        connection,
        "simulation_runs",
        id=ids["run"],
        simulation_id=ids["simulation"],
        tax_benefit_model_version_id=uuid4(),
        status="pending",
        **RUN_VERSIONS,
    )
    insert_row(
        connection,
        "reports",
        id=ids["report"],
        label="Report",
        country="us",
        tax_benefit_model_id=uuid4(),
        inputs="{}",
    )
    insert_row(
        connection,
        "report_runs",
        id=ids["report_run"],
        report_id=ids["report"],
        status="pending",
        trigger="initial",
        **RUN_VERSIONS,
    )
    insert_row(
        connection,
        "report_run_simulation_runs",
        id=uuid4(),
        report_run_id=ids["report_run"],
        simulation_run_id=ids["run"],
        role="baseline",
    )
    insert_row(
        connection,
        "household_jobs",
        id=ids["household_job"],
        country="us",
        household_id=uuid4(),
        year=2026,
        request_data="{}",
        tax_benefit_model_version_id=uuid4(),
        status="pending",
        **RUN_VERSIONS,
    )
    return ids


def test_the_simulation_service_creates_rows_but_writes_no_status_or_result(
    connection: Connection, managed_v2_roles
) -> None:
    _act_as(connection, managed_v2_roles.simulation_service)

    ids = _create_simulation_rows(connection)
    run_count = connection.execute(
        text("SELECT count(*) FROM simulation_runs WHERE id = :id"), {"id": ids["run"]}
    ).scalar_one()
    connection.execute(text("SELECT count(*) FROM policies")).scalar_one()

    assert run_count == 1
    _refused(
        connection,
        "UPDATE simulation_runs SET status = 'running' WHERE id = :id",
        id=ids["run"],
    )
    _refused(
        connection,
        "INSERT INTO poverty (id, simulation_run_id, poverty_type, entity) "
        "VALUES (:id, :run_id, 'spm', 'person')",
        id=uuid4(),
        run_id=ids["run"],
    )
    _refused(connection, "DELETE FROM simulations WHERE id = :id", id=ids["simulation"])
    _refused(
        connection,
        "INSERT INTO report_run_comparisons "
        "(id, report_run_id, baseline_simulation_run_id, reform_simulation_run_id) "
        "VALUES (:id, :report_run_id, :run_id, :run_id)",
        id=uuid4(),
        report_run_id=ids["report_run"],
        run_id=ids["run"],
    )
    _refused(connection, "UPDATE policies SET content_hash = content_hash")


def test_modal_workers_write_their_run_status_and_results_only(
    connection: Connection, managed_v2_roles
) -> None:
    _act_as(connection, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(connection)
    _act_as(connection, managed_v2_roles.modal_worker)

    updated = connection.execute(
        text(
            "UPDATE simulation_runs SET status = 'succeeded', completed_at = now() "
            "WHERE id = :id AND status = 'pending' RETURNING id"
        ),
        {"id": ids["run"]},
    ).scalar_one()
    insert_row(
        connection,
        "poverty",
        id=uuid4(),
        simulation_run_id=ids["run"],
        poverty_type="spm",
        entity="person",
        rate=0.1,
    )
    connection.execute(
        text("UPDATE report_runs SET status = 'running' WHERE id = :id"),
        {"id": ids["report_run"]},
    )
    insert_row(
        connection,
        "report_run_comparisons",
        id=uuid4(),
        report_run_id=ids["report_run"],
        baseline_simulation_run_id=ids["run"],
        reform_simulation_run_id=ids["run"],
        cliff_impact_result="{}",
    )
    connection.execute(
        text(
            "UPDATE household_jobs SET status = 'succeeded', result = '{}', "
            "completed_at = now() WHERE id = :id AND status = 'pending'"
        ),
        {"id": ids["household_job"]},
    )
    connection.execute(text("SELECT count(*) FROM parameter_values")).scalar_one()

    assert updated == ids["run"]
    _refused(
        connection,
        "INSERT INTO simulations (id, simulation_type, dataset_id, "
        "tax_benefit_model_version_id) "
        "VALUES (:id, 'economy', :dataset_id, :version_id)",
        id=uuid4(),
        dataset_id=uuid4(),
        version_id=uuid4(),
    )
    _refused(
        connection, "DELETE FROM poverty WHERE simulation_run_id = :id", id=ids["run"]
    )
    _refused(
        connection,
        "UPDATE poverty SET rate = 0 WHERE simulation_run_id = :id",
        id=ids["run"],
    )
    _refused(connection, "UPDATE households SET content_hash = content_hash")


def test_the_public_api_reads_runs_and_results_but_writes_neither(
    connection: Connection, managed_v2_roles
) -> None:
    _act_as(connection, managed_v2_roles.runtime)

    for table in ("simulation_runs", "report_run_simulation_runs", "poverty"):
        connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    _refused(
        connection,
        "INSERT INTO report_run_simulation_runs "
        "(id, report_run_id, simulation_run_id, role) "
        "VALUES (:id, :report_run_id, :run_id, 'baseline')",
        id=uuid4(),
        report_run_id=uuid4(),
        run_id=uuid4(),
    )
