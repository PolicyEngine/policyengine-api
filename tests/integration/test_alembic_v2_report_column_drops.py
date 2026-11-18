"""Check the report column drops revision against disposable Postgres.

Revision 4e30076d4b9f, on the cliff impacts revision bc334f9877b7, drops what
shared report rows no longer hold: ``reports.label``, ``description`` and
``user_id``, ``report_runs.trigger`` and its four cliff columns, and
``budget_window_runs.trigger``, with the foreign key, index and check that
depend on them. The ``v2_report_run_trigger`` type stays, because
``user_report_run_associations`` uses it. The downgrade adds the columns back
without their values.
"""

from collections.abc import Iterator
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import NullPool

from policyengine_api.data.v2.migration_target import V2_ALEMBIC_DISPOSABLE_TEST
from policyengine_api.data.v2.privilege_reconciliation import (
    DEPLOYMENT_ENVIRONMENT,
    run,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from tests.fixtures.integration.alembic_v2 import (
    alembic_v2_config,
    disposable_v2_url,
)
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    delete_public_api_rows,
    insert_public_api_rows,
    insert_row,
)

CLIFF_IMPACTS_REVISION = "bc334f9877b7"
REPORT_COLUMN_DROPS_REVISION = "4e30076d4b9f"
DROPPED_COLUMNS = {
    "reports": {"label", "description", "user_id"},
    "report_runs": {
        "trigger",
        "baseline_cliff_gap",
        "baseline_cliff_share",
        "reform_cliff_gap",
        "reform_cliff_share",
    },
    "budget_window_runs": {"trigger"},
}


def _schema_shape(engine: Engine) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns, keys, indexes and checks, by name."""
    inspector = inspect(engine)
    return {
        table_name: {
            "columns": {
                column["name"]: (
                    column["type"].compile(dialect=postgresql.dialect()),
                    column["nullable"],
                    column.get("default"),
                )
                for column in inspector.get_columns(table_name)
            },
            "primary_key": inspector.get_pk_constraint(table_name),
            "foreign_keys": {
                key["name"]: (
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    key["options"].get("ondelete"),
                )
                for key in inspector.get_foreign_keys(table_name)
            },
            "unique_constraints": {
                unique["name"]: tuple(unique["column_names"])
                for unique in inspector.get_unique_constraints(table_name)
            },
            "indexes": {
                index["name"]: (
                    tuple(index["column_names"]),
                    index["unique"],
                    index.get("dialect_options", {}).get("postgresql_where"),
                )
                for index in inspector.get_indexes(table_name)
            },
            "checks": {
                check["name"]: check["sqltext"]
                for check in inspector.get_check_constraints(table_name)
            },
        }
        for table_name in inspector.get_table_names(schema="public")
        if table_name != "alembic_version"
    }


def _enum_labels(engine: Engine) -> dict[str, list[str]]:
    """Return each enum type in the public schema with its labels in order."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT type.typname, enum.enumlabel FROM pg_type AS type "
                "JOIN pg_enum AS enum ON enum.enumtypid = type.oid "
                "JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace "
                "WHERE namespace.nspname = 'public' "
                "ORDER BY type.typname, enum.enumsortorder"
            )
        ).all()
    labels: dict[str, list[str]] = {}
    for type_name, label in rows:
        labels.setdefault(type_name, []).append(label)
    return labels


def _without_dropped_schema(
    parent_shape: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the parent's schema less what the revision should remove."""
    expected = deepcopy(parent_shape)
    for table_name, column_names in DROPPED_COLUMNS.items():
        for column_name in column_names:
            del expected[table_name]["columns"][column_name]
    del expected["reports"]["foreign_keys"]["fk_reports_user_id_users"]
    del expected["reports"]["indexes"]["ix_reports_user_id"]
    del expected["report_runs"]["checks"]["ck_report_runs_cliff_impact_complete"]
    return expected


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Yield an engine on the disposable database, left at the v2 head."""
    database_engine = create_engine(disposable_v2_url(), poolclass=NullPool)
    try:
        yield database_engine
    finally:
        command.upgrade(alembic_v2_config(), "head")
        database_engine.dispose()


def test_the_revision_drops_only_the_per_user_and_cliff_schema(engine: Engine) -> None:
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, CLIFF_IMPACTS_REVISION)
    parent_shape = _schema_shape(engine)
    parent_enums = _enum_labels(engine)
    command.upgrade(config, REPORT_COLUMN_DROPS_REVISION)

    assert _schema_shape(engine) == _without_dropped_schema(parent_shape)
    assert _enum_labels(engine) == parent_enums


def test_the_trigger_type_stays_for_each_users_run_records(engine: Engine) -> None:
    command.upgrade(alembic_v2_config(), REPORT_COLUMN_DROPS_REVISION)

    assert _enum_labels(engine)["v2_report_run_trigger"] == [
        "initial",
        "manual",
        "system",
    ]
    record_columns = _schema_shape(engine)["user_report_run_associations"]["columns"]
    assert record_columns["trigger"][0] == "v2_report_run_trigger"


def _store_rows_with_dropped_values(
    connection: Connection, rows: PublicApiRows
) -> dict[str, UUID]:
    """Store a report, its run and its window run, each holding dropped values."""
    ids = {
        name: uuid4()
        for name in ("simulation", "run", "report", "report_run", "window_run")
    }
    insert_row(
        connection,
        "simulations",
        id=ids["simulation"],
        simulation_type="economy",
        dataset_id=rows.dataset_id,
        tax_benefit_model_version_id=rows.version_id,
        year=2026,
    )
    insert_row(
        connection,
        "simulation_runs",
        id=ids["run"],
        simulation_id=ids["simulation"],
        tax_benefit_model_version_id=rows.version_id,
        year=2026,
        status="pending",
        **RUN_VERSIONS,
    )
    insert_row(
        connection,
        "reports",
        id=ids["report"],
        label="Stored label",
        description="Stored description",
        country="us",
        tax_benefit_model_id=rows.model_id,
        inputs="{}",
    )
    insert_row(
        connection,
        "report_runs",
        id=ids["report_run"],
        report_id=ids["report"],
        baseline_simulation_run_id=ids["run"],
        status="pending",
        trigger="initial",
        baseline_cliff_gap=1.0,
        baseline_cliff_share=0.1,
        reform_cliff_gap=2.0,
        reform_cliff_share=0.2,
        **RUN_VERSIONS,
    )
    insert_row(
        connection,
        "budget_window_runs",
        id=ids["window_run"],
        report_id=ids["report"],
        tax_benefit_model_version_id=rows.version_id,
        trigger="manual",
        recalculate=False,
        status="pending",
    )
    return ids


def _delete_stored_rows(connection: Connection, ids: dict[str, UUID]) -> None:
    """Delete the rows; deleting the report deletes its runs."""
    for table, row_id in (
        ("reports", ids["report"]),
        ("simulation_runs", ids["run"]),
        ("simulations", ids["simulation"]),
    ):
        connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})


def test_rows_survive_the_drop_and_a_downgrade_restores_columns_without_values(
    engine: Engine,
) -> None:
    """The columns come back empty: a downgrade can't restore what was dropped."""
    config = alembic_v2_config()
    command.upgrade(config, "head")
    command.downgrade(config, CLIFF_IMPACTS_REVISION)
    parent_shape = _schema_shape(engine)
    with engine.begin() as connection:
        public_api_rows = insert_public_api_rows(connection)
        ids = _store_rows_with_dropped_values(connection, public_api_rows)
    try:
        command.upgrade(config, REPORT_COLUMN_DROPS_REVISION)

        with engine.connect() as connection:
            kept_rows = connection.execute(
                text(
                    "SELECT reports.country, report_runs.status::text, "
                    "budget_window_runs.status::text FROM reports "
                    "JOIN report_runs ON report_runs.report_id = reports.id "
                    "JOIN budget_window_runs "
                    "ON budget_window_runs.report_id = reports.id "
                    "WHERE reports.id = :id"
                ),
                {"id": ids["report"]},
            ).one()
        assert tuple(kept_rows) == ("us", "pending", "pending")

        command.downgrade(config, CLIFF_IMPACTS_REVISION)

        assert _schema_shape(engine) == parent_shape
        with engine.connect() as connection:
            restored_values = connection.execute(
                text(
                    "SELECT reports.label, reports.description, reports.user_id, "
                    "report_runs.trigger, report_runs.baseline_cliff_gap, "
                    "report_runs.baseline_cliff_share, report_runs.reform_cliff_gap, "
                    "report_runs.reform_cliff_share, budget_window_runs.trigger "
                    "FROM reports "
                    "JOIN report_runs ON report_runs.report_id = reports.id "
                    "JOIN budget_window_runs "
                    "ON budget_window_runs.report_id = reports.id "
                    "WHERE reports.id = :id"
                ),
                {"id": ids["report"]},
            ).one()
        assert set(restored_values) == {None}
    finally:
        with engine.begin() as connection:
            _delete_stored_rows(connection, ids)
            delete_public_api_rows(connection, public_api_rows)


def test_the_deploys_grant_steps_pass_and_no_grant_names_a_dropped_column(
    engine: Engine, disposable_v2_database_url: str, managed_v2_roles: Any
) -> None:
    """``apply`` and ``verify`` run after the upgrade on every deploy."""
    command.upgrade(alembic_v2_config(), REPORT_COLUMN_DROPS_REVISION)
    environ = {
        V2_MIGRATION_DATABASE_URL: disposable_v2_database_url,
        V2_ALEMBIC_DISPOSABLE_TEST: "1",
        DEPLOYMENT_ENVIRONMENT: managed_v2_roles.deployment_environment,
    }

    assert run("apply", environ=environ) == 0
    assert run("verify", environ=environ) == 0
    with engine.connect() as connection:
        granted_columns = {
            (table_name, column_name)
            for table_name, column_name in connection.execute(
                text(
                    "SELECT table_name, column_name "
                    "FROM information_schema.column_privileges "
                    "WHERE table_schema = 'public' "
                    "AND table_name IN "
                    "('reports', 'report_runs', 'budget_window_runs')"
                )
            )
        }
    assert (
        not {
            (table_name, column_name)
            for table_name, column_names in DROPPED_COLUMNS.items()
            for column_name in column_names
        }
        & granted_columns
    )
