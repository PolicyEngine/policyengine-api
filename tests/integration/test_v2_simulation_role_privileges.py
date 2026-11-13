"""Run the simulation tables' writes as the roles that do them in production.

The simulation service creates simulations, reports, their runs, budget-window
runs and household jobs; its Modal workers write their runs' status and
results and their budget-window runs' status; the Public API reads them. Each
role holds only its declared privileges
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
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.privileges import (
    CATALOG_WRITER_ROLE,
    ColumnPrivilege,
    TablePrivilege,
    declared_privileges,
)
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


def test_the_simulation_service_creates_rows_and_records_only_its_calls(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    _act_as(connection, managed_v2_roles.simulation_service)

    ids = _create_simulation_rows(connection, public_api_rows)
    run_count = connection.execute(
        text("SELECT count(*) FROM simulation_runs WHERE id = :id"), {"id": ids["run"]}
    ).scalar_one()
    connection.execute(text("SELECT count(*) FROM policies")).scalar_one()

    assert run_count == 1
    # The service records a Modal call's ID once Modal accepts the call, and
    # fails the run when Modal refuses it, while the run is still pending.
    recorded = connection.execute(
        text(
            "UPDATE report_runs SET modal_call_id = 'fc-accepted', "
            "updated_at = now() WHERE id = :id AND status = 'pending' "
            "AND modal_call_id IS NULL RETURNING id"
        ),
        {"id": ids["report_run"]},
    ).scalar_one()
    failed = connection.execute(
        text(
            "UPDATE household_jobs SET status = 'failed', error_message = 'refused', "
            "completed_at = now(), updated_at = now() "
            "WHERE id = :id AND status = 'pending' RETURNING id"
        ),
        {"id": ids["household_job"]},
    ).scalar_one()
    assert (recorded, failed) == (ids["report_run"], ids["household_job"])
    for statement in (
        "UPDATE simulation_runs SET started_at = now() WHERE id = :id",
        "UPDATE simulation_runs SET output_uri = 'gs://bucket/run' WHERE id = :id",
        "UPDATE simulation_runs SET year = 2027 WHERE id = :id",
    ):
        _refused(connection, statement, id=ids["run"])
    _refused(
        connection,
        "UPDATE report_runs SET baseline_cliff_gap = 1.0 WHERE id = :id",
        id=ids["report_run"],
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
            "UPDATE report_runs SET status = 'running', started_at = now(), "
            "modal_call_id = 'fc-coordinator', baseline_cliff_gap = 1.0, "
            "baseline_cliff_share = 0.1, reform_cliff_gap = 2.0, "
            "reform_cliff_share = 0.2, data_version = '1.0.0', "
            "spm_provenance = CAST('{}' AS jsonb), updated_at = now() "
            "WHERE id = :id"
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
    # What a run is stays as the simulation service wrote it.
    for statement, run_key in (
        ("UPDATE simulation_runs SET year = 2027 WHERE id = :id", "run"),
        (
            "UPDATE simulation_runs SET simulation_id = simulation_id WHERE id = :id",
            "run",
        ),
        (
            "UPDATE report_runs SET baseline_simulation_run_id = "
            "baseline_simulation_run_id WHERE id = :id",
            "report_run",
        ),
        ("UPDATE report_runs SET markdown = 'edited' WHERE id = :id", "report_run"),
        (
            "UPDATE household_jobs SET household_id = household_id WHERE id = :id",
            "household_job",
        ),
    ):
        _refused(connection, statement, id=ids[run_key])


def test_modal_workers_insert_withheld_area_codes_that_the_public_api_reads(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    """The workers insert and read the rows, the Public API only reads them.

    The simulation service, the Stage 12 role and the catalog writer can't read
    them.
    """
    _act_as(connection, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(connection, public_api_rows)
    _act_as(connection, managed_v2_roles.modal_worker)
    withheld_code_id = uuid4()

    insert_row(
        connection,
        "withheld_area_codes",
        id=withheld_code_id,
        report_run_id=ids["report_run"],
        baseline_simulation_run_id=ids["run"],
        reform_simulation_run_id=ids["run"],
        area_type="constituency",
        code="E14001063",
    )
    assert (
        connection.execute(
            text("SELECT count(*) FROM withheld_area_codes WHERE report_run_id = :id"),
            {"id": ids["report_run"]},
        ).scalar_one()
        == 1
    )

    # Once written, a withheld code is never changed or removed by the workers.
    _refused(
        connection,
        "UPDATE withheld_area_codes SET code = 'E14001064' WHERE id = :id",
        id=withheld_code_id,
    )
    _refused(
        connection,
        "DELETE FROM withheld_area_codes WHERE id = :id",
        id=withheld_code_id,
    )
    _act_as(connection, managed_v2_roles.runtime)
    assert (
        connection.execute(
            text("SELECT code FROM withheld_area_codes WHERE id = :id"),
            {"id": withheld_code_id},
        ).scalar_one()
        == "E14001063"
    )
    _refused(
        connection,
        "INSERT INTO withheld_area_codes (id, report_run_id, "
        "baseline_simulation_run_id, reform_simulation_run_id, area_type, code) "
        "VALUES (:id, :report_run_id, :run_id, :run_id, 'constituency', 'E14001064')",
        id=uuid4(),
        report_run_id=ids["report_run"],
        run_id=ids["run"],
    )
    for role in (
        managed_v2_roles.simulation_service,
        managed_v2_roles.stage12,
        CATALOG_WRITER_ROLE,
    ):
        _act_as(connection, role)
        _refused(connection, "SELECT count(*) FROM withheld_area_codes")


def test_the_simulation_service_fails_a_window_whose_first_calls_modal_refuses(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    """The service fails a budget-window run when Modal refuses its first years.

    It never sets when the window started, which the Modal workers record, and
    never changes what the window is.
    """
    _act_as(connection, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(connection, public_api_rows)

    failed_window = connection.execute(
        text(
            "UPDATE budget_window_runs SET status = 'failed', "
            "error_message = 'refused', completed_at = now(), updated_at = now() "
            "WHERE id = :id AND status = 'pending' RETURNING id"
        ),
        {"id": ids["budget_window_run"]},
    ).scalar_one()

    assert failed_window == ids["budget_window_run"]
    for statement in (
        "UPDATE budget_window_runs SET started_at = now() WHERE id = :id",
        "UPDATE budget_window_runs SET recalculate = true WHERE id = :id",
        "UPDATE budget_window_runs SET report_id = report_id WHERE id = :id",
    ):
        _refused(connection, statement, id=ids["budget_window_run"])


def test_modal_workers_start_finish_and_fail_budget_windows(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    """The Modal workers write a budget-window run's status and times.

    Each year's coordinator starts the window's next unstarted year when its
    own year finishes; the last year to finish marks the window succeeded, and
    a failed year fails it.
    """
    _act_as(connection, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(connection, public_api_rows)
    failing_window_id = uuid4()
    insert_row(
        connection,
        "budget_window_runs",
        id=failing_window_id,
        report_id=ids["report"],
        tax_benefit_model_version_id=public_api_rows.version_id,
        trigger="manual",
        recalculate=True,
        status="pending",
    )
    _act_as(connection, managed_v2_roles.modal_worker)

    started_windows = [
        connection.execute(
            text(
                "UPDATE budget_window_runs SET status = 'running', "
                "started_at = now(), updated_at = now() "
                "WHERE id = :id AND status = 'pending' RETURNING id"
            ),
            {"id": window_id},
        ).scalar_one()
        for window_id in (ids["budget_window_run"], failing_window_id)
    ]
    succeeded_window = connection.execute(
        text(
            "UPDATE budget_window_runs SET status = 'succeeded', "
            "completed_at = now(), updated_at = now() "
            "WHERE id = :id AND status = 'running' RETURNING id"
        ),
        {"id": ids["budget_window_run"]},
    ).scalar_one()
    failed_window = connection.execute(
        text(
            "UPDATE budget_window_runs SET status = 'failed', "
            "error_message = 'the 2027 report run failed', completed_at = now(), "
            "updated_at = now() WHERE id = :id AND status = 'running' RETURNING id"
        ),
        {"id": failing_window_id},
    ).scalar_one()

    assert started_windows == [ids["budget_window_run"], failing_window_id]
    assert (succeeded_window, failed_window) == (
        ids["budget_window_run"],
        failing_window_id,
    )
    for statement in (
        "UPDATE budget_window_runs SET trigger = 'manual' WHERE id = :id",
        "UPDATE budget_window_runs SET recalculate = false WHERE id = :id",
        "UPDATE budget_window_runs SET tax_benefit_model_version_id = "
        "tax_benefit_model_version_id WHERE id = :id",
    ):
        _refused(connection, statement, id=ids["budget_window_run"])


@pytest.mark.parametrize("role_kind", ["simulation_service", "modal_worker"])
def test_each_simulation_role_locks_a_budget_window_run_row(
    connection: Connection,
    managed_v2_roles,
    public_api_rows: PublicApiRows,
    role_kind: str,
) -> None:
    """Either role may lock a window's row, for example before changing its status.

    PostgreSQL lets a role lock a row ``FOR UPDATE`` when it may update some of
    the table's columns. A lock over a join with ``reports`` names
    ``budget_window_runs`` alone: neither role may update ``reports``, so a lock
    on every joined table is refused.
    """
    _act_as(connection, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(connection, public_api_rows)
    _act_as(connection, getattr(managed_v2_roles, role_kind))

    locked_window = connection.execute(
        text("SELECT id FROM budget_window_runs WHERE id = :id FOR UPDATE"),
        {"id": ids["budget_window_run"]},
    ).scalar_one()
    locked_over_join = connection.execute(
        text(
            "SELECT budget_window_runs.id, reports.budget_window_size "
            "FROM budget_window_runs JOIN reports "
            "ON reports.id = budget_window_runs.report_id "
            "WHERE budget_window_runs.id = :id FOR UPDATE OF budget_window_runs"
        ),
        {"id": ids["budget_window_run"]},
    ).one()

    assert locked_window == ids["budget_window_run"]
    assert tuple(locked_over_join) == (ids["budget_window_run"], 1)
    _refused(
        connection,
        "SELECT budget_window_runs.id FROM budget_window_runs JOIN reports "
        "ON reports.id = budget_window_runs.report_id "
        "WHERE budget_window_runs.id = :id FOR UPDATE",
        id=ids["budget_window_run"],
    )


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


@pytest.mark.parametrize("role_kind", ["simulation_service", "modal_worker"])
def test_each_simulation_role_updates_exactly_its_declared_columns(
    connection: Connection, managed_v2_roles, role_kind: str
) -> None:
    """Every column of the run tables is updatable exactly when it is declared."""
    role = getattr(managed_v2_roles, role_kind)
    declared = declared_privileges(managed_v2_roles.deployment_environment)[role]
    _act_as(connection, role)

    for table in (
        "simulation_runs",
        "report_runs",
        "household_jobs",
        "budget_window_runs",
    ):
        updatable = {
            column
            for privilege in declared[table]
            if isinstance(privilege, ColumnPrivilege)
            and privilege.privilege is TablePrivilege.UPDATE
            for column in privilege.columns
        }
        for column in V2_METADATA.tables[table].c:
            # The privilege is checked when the statement starts, so no row is
            # needed.
            statement = f"UPDATE {table} SET {column.name} = {column.name} WHERE false"
            if column.name in updatable:
                connection.execute(text(statement))
            else:
                _refused(connection, statement)
