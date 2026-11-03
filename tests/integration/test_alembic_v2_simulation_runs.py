"""Check the simulation runs revisions against disposable Postgres.

Five revisions follow the area impact coordinate removal. The first adds
simulation runs and the table naming the simulation runs a report run
combines, keys every result table by run, and gives household jobs one
household, one year and one policy. The second drops the foreign keys from
those tables to the Public API's tables. The third adds the economy output's
fields that had no column. The fourth makes each result row tell apart its
pair of simulation runs, decile grouping and poverty group. The fifth moves
the parts of a comparison without a result table from the report run to one
row per compared pair. None changes any other table, so the previous Public
API revision, whose roles can't read or write any table they change, keeps
working while they are deployed.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from policyengine_api.constants import REPO
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from tests.integration.simulation_rows import RUN_VERSIONS, insert_row, refused

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

SIMULATION_RUNS_PREVIOUS_REVISION = "c614b6bcccfc"
SIMULATION_RUNS_REVISION = "2ffd50f47a2b"
CROSS_SERVICE_KEYS_REVISION = "7a83a87d029a"
ECONOMY_OUTPUT_REVISION = "7f43d2c7c3c6"
RESULT_IDENTITY_REVISION = "2e3de7c572ed"
NEW_TABLES = frozenset(
    {"simulation_runs", "report_run_simulation_runs", "report_run_comparisons"}
)
CHANGED_TABLES = frozenset(
    {
        "budget_summary",
        "congressional_district_impacts",
        "constituency_impacts",
        "decile_impacts",
        "household_jobs",
        "inequality",
        "intra_decile_impacts",
        "local_authority_impacts",
        "poverty",
        "program_statistics",
        "report_runs",
        "reports",
        "simulations",
    }
)
# The tables the simulation service and its Modal workers write; the Public API
# writes every other table.
SIMULATION_SIDE_TABLES = (
    CHANGED_TABLES | NEW_TABLES | {"aggregates", "change_aggregates"}
)
SHA256_HEX = "a" * 64
COMPLETED_AT = "2026-11-04T00:00:00Z"


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(V2_ALEMBIC_DISPOSABLE_TEST, ""),
        }
    )
    if not settings.disposable_test:
        pytest.fail("v2 lifecycle tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


@pytest.fixture
def config() -> Config:
    return Config(str(REPO / "alembic-v2.ini"))


@pytest.fixture
def engine(config: Config) -> Iterator[Engine]:
    database_engine = create_engine(_disposable_url())
    try:
        yield database_engine
    finally:
        command.upgrade(config, "head")
        database_engine.dispose()


@pytest.fixture
def connection(config: Config, engine: Engine) -> Iterator[Connection]:
    """Yield a connection at head whose writes are rolled back after the test."""
    command.upgrade(config, "head")
    with engine.connect() as database_connection:
        transaction = database_connection.begin()
        try:
            yield database_connection
        finally:
            transaction.rollback()


def _table_shape(engine: Engine, table_name: str) -> dict[str, object]:
    """Describe one table's columns, keys, indexes and checks for comparison."""
    inspector = inspect(engine)
    return {
        "columns": [
            (column["name"], str(column["type"]), column["nullable"], column["default"])
            for column in inspector.get_columns(table_name)
        ],
        "primary_key": inspector.get_pk_constraint(table_name),
        "foreign_keys": sorted(
            inspector.get_foreign_keys(table_name), key=lambda key: key["name"]
        ),
        "indexes": sorted(
            inspector.get_indexes(table_name), key=lambda index: index["name"]
        ),
        "unique_constraints": sorted(
            inspector.get_unique_constraints(table_name),
            key=lambda constraint: constraint["name"],
        ),
        "check_constraints": sorted(
            inspector.get_check_constraints(table_name),
            key=lambda constraint: constraint["name"],
        ),
    }


def _shapes(engine: Engine) -> dict[str, dict[str, object]]:
    return {
        table_name: _table_shape(engine, table_name)
        for table_name in inspect(engine).get_table_names(schema="public")
    }


def _column_names(engine: Engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def _enum_type_names(engine: Engine) -> set[str]:
    with engine.connect() as type_connection:
        return set(
            type_connection.execute(
                text("SELECT typname FROM pg_type WHERE typtype = 'e'")
            ).scalars()
        )


def test_the_revisions_add_two_tables_and_change_only_simulation_side_tables(
    config: Config, engine: Engine
) -> None:
    command.downgrade(config, SIMULATION_RUNS_PREVIOUS_REVISION)
    before = _shapes(engine)
    command.upgrade(config, "head")
    after = _shapes(engine)

    assert set(after) - set(before) == NEW_TABLES
    assert set(before) <= set(after)
    changed = {
        table_name for table_name in before if before[table_name] != after[table_name]
    }
    assert changed == CHANGED_TABLES


def test_each_revision_downgrades_to_its_parent_and_upgrades_again(
    config: Config, engine: Engine
) -> None:
    command.upgrade(config, "head")

    command.downgrade(config, RESULT_IDENTITY_REVISION)
    assert "report_run_comparisons" not in inspect(engine).get_table_names()
    assert {"labor_supply_result", "data_version"} <= _column_names(
        engine, "report_runs"
    )

    command.downgrade(config, ECONOMY_OUTPUT_REVISION)
    assert "decile_variable" not in _column_names(engine, "decile_impacts")
    assert "filter_group" not in _column_names(engine, "poverty")
    budget_key = next(
        constraint
        for constraint in inspect(engine).get_unique_constraints("budget_summary")
        if constraint["name"] == "uq_budget_summary_run_variable_entity"
    )
    assert budget_key["column_names"] == ["report_run_id", "variable_name", "entity"]

    command.downgrade(config, CROSS_SERVICE_KEYS_REVISION)
    assert {"spm_provenance", "data_version"}.isdisjoint(
        _column_names(engine, "report_runs")
    )
    program_entity = next(
        column
        for column in inspect(engine).get_columns("program_statistics")
        if column["name"] == "entity"
    )
    assert not program_entity["nullable"]

    command.downgrade(config, SIMULATION_RUNS_REVISION)
    assert {"datasets", "households", "policies"} <= {
        key["referred_table"] for key in inspect(engine).get_foreign_keys("simulations")
    }

    command.downgrade(config, SIMULATION_RUNS_PREVIOUS_REVISION)
    assert NEW_TABLES.isdisjoint(inspect(engine).get_table_names(schema="public"))
    assert {"status", "household_result", "output_dataset_id"} <= _column_names(
        engine, "simulations"
    )
    assert {"report_run_id", "simulation_id"} <= _column_names(engine, "poverty")
    enum_types = _enum_type_names(engine)
    assert "v2_simulation_status" in enum_types
    assert "v2_simulation_role" not in enum_types

    command.upgrade(config, "head")
    command.check(config)
    assert "v2_simulation_role" in _enum_type_names(engine)


def test_head_has_no_foreign_key_between_the_two_services_tables(
    config: Config, engine: Engine
) -> None:
    command.upgrade(config, "head")
    inspector = inspect(engine)

    cross_service_keys = sorted(
        f"{table_name}.{key['name']} -> {key['referred_table']}"
        for table_name in inspector.get_table_names(schema="public")
        for key in inspector.get_foreign_keys(table_name)
        if (table_name in SIMULATION_SIDE_TABLES)
        != (key["referred_table"] in SIMULATION_SIDE_TABLES)
    )

    assert cross_service_keys == []


def _count(connection: Connection, table: str, column: str, value: object) -> int:
    return connection.execute(
        text(f"SELECT count(*) FROM {table} WHERE {column} = :value"),
        {"value": value},
    ).scalar_one()


def _insert_simulation(connection: Connection) -> object:
    """Store an economy simulation; its catalog references need no catalog rows."""
    simulation_id = uuid4()
    insert_row(
        connection,
        "simulations",
        id=simulation_id,
        simulation_type="economy",
        dataset_id=uuid4(),
        tax_benefit_model_version_id=uuid4(),
        year=2026,
    )
    return simulation_id


def _insert_simulation_run(
    connection: Connection,
    simulation_id: object,
    *,
    status: str = "pending",
    **values: object,
) -> object:
    run_id = uuid4()
    insert_row(
        connection,
        "simulation_runs",
        id=run_id,
        simulation_id=simulation_id,
        tax_benefit_model_version_id=uuid4(),
        status=status,
        **RUN_VERSIONS,
        **values,
    )
    return run_id


def _insert_report_run(connection: Connection) -> object:
    report_id, report_run_id = uuid4(), uuid4()
    insert_row(
        connection,
        "reports",
        id=report_id,
        label="Report",
        country="us",
        tax_benefit_model_id=uuid4(),
        inputs="{}",
    )
    insert_row(
        connection,
        "report_runs",
        id=report_run_id,
        report_id=report_id,
        status="running",
        trigger="initial",
        **RUN_VERSIONS,
    )
    return report_run_id


def test_simulation_runs_need_a_completion_time_and_a_whole_output(
    connection: Connection,
) -> None:
    simulation_id = _insert_simulation(connection)
    run_id = _insert_simulation_run(connection, simulation_id)

    with refused(connection):
        connection.execute(
            text("UPDATE simulation_runs SET status = 'succeeded' WHERE id = :id"),
            {"id": run_id},
        )
    with refused(connection):
        _insert_simulation_run(
            connection, simulation_id, output_uri="gs://bucket/run.parquet"
        )
    with refused(connection):
        _insert_simulation_run(
            connection,
            simulation_id,
            output_uri="gs://bucket/run.parquet",
            output_sha256="short",
        )
    finished_run_id = _insert_simulation_run(
        connection,
        simulation_id,
        status="succeeded",
        completed_at=COMPLETED_AT,
        output_uri="gs://bucket/run.parquet",
        output_sha256=SHA256_HEX,
    )
    insert_row(
        connection,
        "poverty",
        id=uuid4(),
        simulation_run_id=finished_run_id,
        poverty_type="spm",
        entity="person",
    )

    connection.execute(
        text("DELETE FROM simulations WHERE id = :id"), {"id": simulation_id}
    )
    assert _count(connection, "simulation_runs", "simulation_id", simulation_id) == 0
    assert _count(connection, "poverty", "simulation_run_id", finished_run_id) == 0


def test_report_run_members_are_unique_and_keep_their_simulation_runs(
    connection: Connection,
) -> None:
    run_id = _insert_simulation_run(connection, _insert_simulation(connection))
    report_run_id = _insert_report_run(connection)
    member = {
        "report_run_id": report_run_id,
        "simulation_run_id": run_id,
        "role": "baseline",
    }
    insert_row(connection, "report_run_simulation_runs", id=uuid4(), **member)

    with refused(connection):
        insert_row(connection, "report_run_simulation_runs", id=uuid4(), **member)
    with refused(connection):
        connection.execute(
            text("DELETE FROM simulation_runs WHERE id = :id"), {"id": run_id}
        )
    connection.execute(
        text("DELETE FROM report_runs WHERE id = :id"), {"id": report_run_id}
    )
    assert (
        _count(connection, "report_run_simulation_runs", "report_run_id", report_run_id)
        == 0
    )


def test_results_are_unique_per_run_and_name_runs_that_exist(
    connection: Connection,
) -> None:
    simulation_id = _insert_simulation(connection)
    baseline_run_id = _insert_simulation_run(connection, simulation_id)
    reform_run_id = _insert_simulation_run(connection, simulation_id)
    comparison_runs = {
        "report_run_id": _insert_report_run(connection),
        "baseline_simulation_run_id": baseline_run_id,
        "reform_simulation_run_id": reform_run_id,
    }

    with refused(connection):
        insert_row(
            connection,
            "budget_summary",
            id=uuid4(),
            variable_name="household_net_income",
            entity="household",
            **{**comparison_runs, "reform_simulation_run_id": uuid4()},
        )
    poverty = {
        "simulation_run_id": reform_run_id,
        "poverty_type": "spm",
        "entity": "person",
    }
    insert_row(connection, "poverty", id=uuid4(), **poverty)
    with refused(connection):
        insert_row(connection, "poverty", id=uuid4(), **poverty)
    for group in ("child", "adult"):
        insert_row(
            connection,
            "poverty",
            id=uuid4(),
            filter_variable="age",
            filter_group=group,
            **poverty,
        )
    decile = {
        "income_variable": "household_net_income",
        "entity": "household",
        "decile": 1,
        "quantiles": 10,
        **comparison_runs,
    }
    insert_row(connection, "decile_impacts", id=uuid4(), **decile)
    insert_row(
        connection,
        "decile_impacts",
        id=uuid4(),
        decile_variable="household_wealth_decile",
        **decile,
    )
    with refused(connection):
        insert_row(connection, "decile_impacts", id=uuid4(), **decile)
    budget = {"variable_name": "household_tax", "entity": "household"}
    insert_row(connection, "budget_summary", id=uuid4(), **budget, **comparison_runs)
    next_year_runs = {
        **comparison_runs,
        "baseline_simulation_run_id": _insert_simulation_run(connection, simulation_id),
        "reform_simulation_run_id": _insert_simulation_run(connection, simulation_id),
    }
    insert_row(connection, "budget_summary", id=uuid4(), **budget, **next_year_runs)
    with refused(connection):
        insert_row(connection, "budget_summary", id=uuid4(), **budget, **next_year_runs)
    # One comparison row per compared pair holds the untabled parts.
    for runs in (comparison_runs, next_year_runs):
        insert_row(
            connection,
            "report_run_comparisons",
            id=uuid4(),
            labor_supply_result="{}",
            data_version="1.0.0",
            **runs,
        )
    with refused(connection):
        insert_row(connection, "report_run_comparisons", id=uuid4(), **next_year_runs)
    insert_row(
        connection,
        "program_statistics",
        id=uuid4(),
        program_name="income_tax",
        **comparison_runs,
    )
    with refused(connection):
        insert_row(
            connection,
            "program_statistics",
            id=uuid4(),
            program_name="income_tax",
            **comparison_runs,
        )
    constituency = {
        "constituency_name": "Aldershot",
        "average_household_income_change": 1.0,
        "relative_household_income_change": 0.01,
        "population": 100.0,
        **comparison_runs,
    }
    insert_row(
        connection,
        "constituency_impacts",
        id=uuid4(),
        constituency_code="E14000530",
        disclosure_tier="approximate",
        **constituency,
    )
    with refused(connection):
        insert_row(
            connection,
            "constituency_impacts",
            id=uuid4(),
            constituency_code="E14000531",
            disclosure_tier="withheld",
            **constituency,
        )


def test_household_jobs_take_a_valid_year_and_record_when_they_end(
    connection: Connection,
) -> None:
    household_job = {
        "country": "us",
        "household_id": uuid4(),
        "request_data": "{}",
        "tax_benefit_model_version_id": uuid4(),
        **RUN_VERSIONS,
    }
    insert_row(
        connection,
        "household_jobs",
        id=uuid4(),
        year=2026,
        status="pending",
        **household_job,
    )

    with refused(connection):
        insert_row(
            connection,
            "household_jobs",
            id=uuid4(),
            year=1800,
            status="pending",
            **household_job,
        )
    with refused(connection):
        insert_row(
            connection,
            "household_jobs",
            id=uuid4(),
            year=2026,
            status="failed",
            **household_job,
        )
