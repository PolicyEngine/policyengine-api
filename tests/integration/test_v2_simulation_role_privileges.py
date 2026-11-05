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
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    insert_public_api_rows,
    insert_row,
    refused,
)

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


@pytest.fixture
def public_api_rows(connection: Connection) -> PublicApiRows:
    """Store, as the superuser, the Public API's rows the simulation rows name."""
    return insert_public_api_rows(connection)


def _act_as(connection: Connection, role: str) -> None:
    quoted_role = connection.dialect.identifier_preparer.quote(role)
    connection.execute(text(f"SET LOCAL ROLE {quoted_role}"))


def _refused(connection: Connection, statement: str, **values: object) -> None:
    """Expect a permission error from ``statement``."""
    with refused(connection, ProgrammingError, match="permission denied"):
        connection.execute(text(statement), values)


def _create_simulation_rows(
    connection: Connection, public_api_rows: PublicApiRows
) -> dict[str, object]:
    """Create what the simulation API creates for one economy report run."""
    ids = {
        name: uuid4()
        for name in (
            "simulation",
            "run",
            "report",
            "budget_window_run",
            "report_run",
            "household_job",
        )
    }
    insert_row(
        connection,
        "simulations",
        id=ids["simulation"],
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
    )
    insert_row(
        connection,
        "simulation_runs",
        id=ids["run"],
        simulation_id=ids["simulation"],
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
        status="pending",
        **RUN_VERSIONS,
    )
    insert_row(
        connection,
        "reports",
        id=ids["report"],
        label="Report",
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        year=2026,
        budget_window_size=1,
        inputs="{}",
    )
    insert_row(
        connection,
        "budget_window_runs",
        id=ids["budget_window_run"],
        report_id=ids["report"],
        tax_benefit_model_version_id=public_api_rows.version_id,
        trigger="initial",
        recalculate=False,
        status="pending",
    )
    insert_row(
        connection,
        "report_runs",
        id=ids["report_run"],
        report_id=ids["report"],
        budget_window_run_id=ids["budget_window_run"],
        year=2026,
        baseline_simulation_run_id=ids["run"],
        status="pending",
        trigger="initial",
        **RUN_VERSIONS,
    )
    insert_row(
        connection,
        "household_jobs",
        id=ids["household_job"],
        country="us",
        household_id=public_api_rows.household_id,
        year=2026,
        request_data="{}",
        tax_benefit_model_version_id=public_api_rows.version_id,
        status="pending",
        **RUN_VERSIONS,
    )
    return ids


def test_the_simulation_service_creates_rows_but_writes_no_status_or_result(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    _act_as(connection, managed_v2_roles.simulation_service)

    ids = _create_simulation_rows(connection, public_api_rows)
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
        "INSERT INTO labor_supply_decile_responses (id, report_run_id, decile) "
        "VALUES (:id, :report_run_id, 1)",
        id=uuid4(),
        report_run_id=ids["report_run"],
    )
    _refused(connection, "UPDATE policies SET content_hash = content_hash")


def test_modal_workers_write_their_run_status_and_results_only(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    _act_as(connection, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(connection, public_api_rows)
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
        text(
            "UPDATE report_runs SET status = 'running', baseline_cliff_gap = 1.0, "
            "baseline_cliff_share = 0.1, reform_cliff_gap = 2.0, "
            "reform_cliff_share = 0.2 WHERE id = :id"
        ),
        {"id": ids["report_run"]},
    )
    insert_row(
        connection,
        "labor_supply_decile_responses",
        id=uuid4(),
        report_run_id=ids["report_run"],
        decile=1,
        average_income_effect=-1.0,
    )
    finished_job = connection.execute(
        text(
            "UPDATE household_jobs SET status = 'succeeded', result = '{}', "
            "completed_at = now() WHERE id = :id AND status = 'pending' "
            "RETURNING id"
        ),
        {"id": ids["household_job"]},
    ).scalar_one()
    connection.execute(text("SELECT count(*) FROM parameter_values")).scalar_one()

    assert updated == ids["run"]
    assert finished_job == ids["household_job"]
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
        "INSERT INTO budget_window_runs (id, report_id, "
        "tax_benefit_model_version_id, trigger, recalculate, status) "
        "VALUES (:id, :report_id, :version_id, 'manual', true, 'pending')",
        id=uuid4(),
        report_id=ids["report"],
        version_id=public_api_rows.version_id,
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

    for table in ("simulation_runs", "report_runs", "poverty"):
        connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    _refused(
        connection,
        "INSERT INTO report_runs (id, report_id, baseline_simulation_run_id, "
        "country_package_version, policyengine_version, status, trigger) "
        "VALUES (:id, :report_id, :run_id, '1.0.0', '4.0.0', 'pending', 'initial')",
        id=uuid4(),
        report_id=uuid4(),
        run_id=uuid4(),
    )
