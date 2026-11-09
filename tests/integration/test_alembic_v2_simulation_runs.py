"""Check the simulation runs revision against disposable Postgres.

One revision follows the parameter search file revision. It adds simulation
runs, one per simulation and year; has each report run name its baseline and
reform simulation runs; keys every result table by run; types a report run's
cliff impact and labour supply; adds the budget-window tables; gives household
jobs one household, one year and one policy; and adds the economy output's
fields that had no column. The foreign keys from those tables to the Public
API's tables stay, and the new columns that name the Public API's rows get
keys too. It changes no other table. The previous Public API revision keeps
working while it is deployed: its roles can't read or write any table it
changes, except the catalog writer, which counts the rows of simulations,
reports and report_runs.
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
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    insert_public_api_rows,
    insert_row,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

# The catalog pruning revision, the simulation runs revision's parent.
SIMULATION_RUNS_PREVIOUS_REVISION = "334859ef4fec"
NEW_TABLES = frozenset(
    {
        "simulation_runs",
        "budget_window_runs",
        "labor_supply_responses",
        "labor_supply_decile_responses",
    }
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
# The foreign keys from the simulation service's tables to the Public API's
# rows, with their delete rules.
PUBLIC_API_FOREIGN_KEYS = {
    ("simulations", "dataset_id"): ("datasets", "RESTRICT"),
    ("simulations", "household_id"): ("households", "RESTRICT"),
    ("simulations", "policy_id"): ("policies", "SET NULL"),
    ("simulations", "dynamic_id"): ("dynamics", "SET NULL"),
    ("simulations", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("simulations", "region_id"): ("regions", "SET NULL"),
    ("reports", "user_id"): ("users", "SET NULL"),
    ("reports", "tax_benefit_model_id"): ("tax_benefit_models", "RESTRICT"),
    ("reports", "policy_id"): ("policies", "SET NULL"),
    ("reports", "household_id"): ("households", "RESTRICT"),
    ("reports", "dataset_id"): ("datasets", "SET NULL"),
    ("reports", "region_id"): ("regions", "SET NULL"),
    ("simulation_runs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("simulation_runs", "dataset_id"): ("datasets", "RESTRICT"),
    ("simulation_runs", "region_id"): ("regions", "SET NULL"),
    ("household_jobs", "household_id"): ("households", "RESTRICT"),
    ("household_jobs", "policy_id"): ("policies", "SET NULL"),
    ("household_jobs", "dynamic_id"): ("dynamics", "SET NULL"),
    ("household_jobs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("budget_window_runs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
}
LABOR_SUPPLY_RESPONSE_COLUMNS = (
    "income_effect_earnings_change",
    "substitution_effect_earnings_change",
    "total_earnings_change",
    "revenue_change",
    "relative_income_effect",
    "relative_substitution_effect",
    "baseline_weekly_hours",
    "reform_weekly_hours",
    "weekly_hours_change",
    "weekly_hours_income_effect",
    "weekly_hours_substitution_effect",
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


def test_the_revision_downgrades_to_its_parent_and_upgrades_again(
    config: Config, engine: Engine
) -> None:
    """The revision adds its tables and changes only simulation-side tables."""
    command.upgrade(config, "head")

    command.downgrade(config, SIMULATION_RUNS_PREVIOUS_REVISION)
    before = _shapes(engine)
    assert NEW_TABLES.isdisjoint(before)
    assert {"status", "household_result", "output_dataset_id"} <= _column_names(
        engine, "simulations"
    )
    assert {"report_run_id", "simulation_id"} <= _column_names(engine, "poverty")
    assert {"datasets", "households", "policies"} <= {
        key["referred_table"] for key in inspect(engine).get_foreign_keys("simulations")
    }
    program_entity = next(
        column
        for column in inspect(engine).get_columns("program_statistics")
        if column["name"] == "entity"
    )
    assert not program_entity["nullable"]
    assert "v2_simulation_status" in _enum_type_names(engine)

    command.upgrade(config, "head")
    command.check(config)
    after = _shapes(engine)
    assert set(after) - set(before) == NEW_TABLES
    assert set(before) <= set(after)
    changed = {
        table_name for table_name in before if before[table_name] != after[table_name]
    }
    assert changed == CHANGED_TABLES
    assert {"baseline_simulation_run_id", "reform_simulation_run_id"} <= (
        _column_names(engine, "report_runs")
    )


def test_head_keeps_the_foreign_keys_to_the_public_api_tables(
    config: Config, engine: Engine
) -> None:
    """Each service writes only its own tables; the keys between them stay."""
    command.upgrade(config, "head")
    inspector = inspect(engine)

    public_api_keys = {
        (table_name, column_name): (key["referred_table"], key["options"]["ondelete"])
        for table_name in SIMULATION_SIDE_TABLES
        for key in inspector.get_foreign_keys(table_name)
        if key["referred_table"] not in SIMULATION_SIDE_TABLES
        for column_name in key["constrained_columns"]
    }

    assert public_api_keys == PUBLIC_API_FOREIGN_KEYS
    assert {"ix_reports_user_id"} <= {
        index["name"] for index in inspector.get_indexes("reports")
    }


def _count(connection: Connection, table: str, column: str, value: object) -> int:
    return connection.execute(
        text(f"SELECT count(*) FROM {table} WHERE {column} = :value"),
        {"value": value},
    ).scalar_one()


@pytest.fixture
def public_api_rows(connection: Connection) -> PublicApiRows:
    return insert_public_api_rows(connection)


def _insert_simulation(
    connection: Connection, public_api_rows: PublicApiRows
) -> object:
    """Store an economy simulation of the stored dataset and catalog version."""
    simulation_id = uuid4()
    insert_row(
        connection,
        "simulations",
        id=simulation_id,
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
    )
    return simulation_id


def _insert_simulation_run(
    connection: Connection,
    simulation_id: object,
    *,
    status: str = "pending",
    year: int = 2026,
    **values: object,
) -> object:
    """Store a run of the simulation for ``year`` on its catalog version."""
    run_id = uuid4()
    version_id = connection.execute(
        text("SELECT tax_benefit_model_version_id FROM simulations WHERE id = :id"),
        {"id": simulation_id},
    ).scalar_one()
    insert_row(
        connection,
        "simulation_runs",
        id=run_id,
        simulation_id=simulation_id,
        tax_benefit_model_version_id=version_id,
        status=status,
        year=year,
        **RUN_VERSIONS,
        **values,
    )
    return run_id


def _insert_report_run(
    connection: Connection,
    public_api_rows: PublicApiRows,
    baseline_run_id: object,
    reform_run_id: object | None = None,
) -> object:
    """Store a report and one run of it comparing the two simulation runs."""
    report_id, report_run_id = uuid4(), uuid4()
    insert_row(
        connection,
        "reports",
        id=report_id,
        label="Report",
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        inputs="{}",
    )
    insert_row(
        connection,
        "report_runs",
        id=report_run_id,
        report_id=report_id,
        baseline_simulation_run_id=baseline_run_id,
        reform_simulation_run_id=reform_run_id,
        status="running",
        trigger="initial",
        **RUN_VERSIONS,
    )
    return report_run_id


def test_rows_naming_a_missing_public_api_row_are_refused(
    connection: Connection, public_api_rows: PublicApiRows
) -> None:
    """PostgreSQL checks each row a simulation-side row names when it is written."""
    simulation_id = _insert_simulation(connection, public_api_rows)

    with refused(connection, match="foreign key constraint"):
        insert_row(
            connection,
            "simulation_runs",
            id=uuid4(),
            simulation_id=simulation_id,
            tax_benefit_model_version_id=uuid4(),
            status="pending",
            year=2026,
            **RUN_VERSIONS,
        )
    with refused(connection, match="foreign key constraint"):
        insert_row(
            connection,
            "household_jobs",
            id=uuid4(),
            country="us",
            household_id=uuid4(),
            year=2026,
            request_data="{}",
            tax_benefit_model_version_id=public_api_rows.version_id,
            status="pending",
            **RUN_VERSIONS,
        )


def test_simulation_runs_need_a_completion_time_and_a_whole_output(
    connection: Connection, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _insert_simulation(connection, public_api_rows)
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


def test_report_runs_name_a_baseline_run_and_keep_their_simulation_runs(
    connection: Connection, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _insert_simulation(connection, public_api_rows)
    baseline_run_id = _insert_simulation_run(connection, simulation_id)
    reform_run_id = _insert_simulation_run(connection, simulation_id)

    with refused(connection, match="baseline_simulation_run_id"):
        _insert_report_run(connection, public_api_rows, None)
    with refused(connection, match="foreign key constraint"):
        _insert_report_run(connection, public_api_rows, uuid4())
    # A household report with only a baseline names no reform run.
    _insert_report_run(connection, public_api_rows, baseline_run_id)
    report_run_id = _insert_report_run(
        connection, public_api_rows, baseline_run_id, reform_run_id
    )
    for run_id in (baseline_run_id, reform_run_id):
        with refused(connection, match="foreign key constraint"):
            connection.execute(
                text("DELETE FROM simulation_runs WHERE id = :id"), {"id": run_id}
            )
    connection.execute(
        text("DELETE FROM report_runs WHERE id = :id"), {"id": report_run_id}
    )
    assert _count(connection, "simulation_runs", "id", reform_run_id) == 1


def test_results_are_unique_per_run_and_name_runs_that_exist(
    connection: Connection, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _insert_simulation(connection, public_api_rows)
    baseline_run_id = _insert_simulation_run(connection, simulation_id)
    reform_run_id = _insert_simulation_run(connection, simulation_id)
    comparison_runs = {
        "report_run_id": _insert_report_run(
            connection, public_api_rows, baseline_run_id, reform_run_id
        ),
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
    # A report run compares one pair, so its rows are unique within it.
    with refused(connection):
        insert_row(
            connection,
            "budget_summary",
            id=uuid4(),
            **budget,
            **{**comparison_runs, "reform_simulation_run_id": baseline_run_id},
        )
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


def test_a_report_runs_labor_supply_and_cliff_impact_are_typed(
    connection: Connection, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _insert_simulation(connection, public_api_rows)
    report_run_id = _insert_report_run(
        connection,
        public_api_rows,
        _insert_simulation_run(connection, simulation_id),
        _insert_simulation_run(connection, simulation_id),
    )
    response = dict.fromkeys(LABOR_SUPPLY_RESPONSE_COLUMNS, 1.0)

    insert_row(
        connection,
        "labor_supply_responses",
        id=uuid4(),
        report_run_id=report_run_id,
        **response,
    )
    with refused(connection):
        insert_row(
            connection,
            "labor_supply_responses",
            id=uuid4(),
            report_run_id=report_run_id,
            **response,
        )
    # .py reports a relative response only for deciles above zero.
    insert_row(
        connection,
        "labor_supply_decile_responses",
        id=uuid4(),
        report_run_id=report_run_id,
        decile=0,
        average_income_effect=-1.0,
        average_substitution_effect=2.0,
    )
    insert_row(
        connection,
        "labor_supply_decile_responses",
        id=uuid4(),
        report_run_id=report_run_id,
        decile=1,
        average_income_effect=-1.0,
        average_substitution_effect=2.0,
        relative_income_effect=-0.01,
        relative_substitution_effect=0.02,
    )
    with refused(connection):
        insert_row(
            connection,
            "labor_supply_decile_responses",
            id=uuid4(),
            report_run_id=report_run_id,
            decile=1,
        )
    with refused(connection, match="ck_report_runs_cliff_impact_complete"):
        connection.execute(
            text("UPDATE report_runs SET baseline_cliff_gap = 1.0 WHERE id = :id"),
            {"id": report_run_id},
        )
    connection.execute(
        text(
            "UPDATE report_runs SET baseline_cliff_gap = 1.0, "
            "baseline_cliff_share = 0.1, reform_cliff_gap = 2.0, "
            "reform_cliff_share = 0.2, data_version = '1.0.0', "
            "spm_provenance = CAST(:receipt AS jsonb) WHERE id = :id"
        ),
        {"id": report_run_id, "receipt": '{"source": "census"}'},
    )
    receipt_type = connection.execute(
        text("SELECT jsonb_typeof(spm_provenance) FROM report_runs WHERE id = :id"),
        {"id": report_run_id},
    ).scalar_one()
    assert receipt_type == "object"

    connection.execute(
        text("DELETE FROM report_runs WHERE id = :id"), {"id": report_run_id}
    )
    for table in ("labor_supply_responses", "labor_supply_decile_responses"):
        assert _count(connection, table, "report_run_id", report_run_id) == 0


def _insert_report(
    connection: Connection, public_api_rows: PublicApiRows, **values: object
) -> object:
    report_id = uuid4()
    insert_row(
        connection,
        "reports",
        id=report_id,
        label="Budget window",
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        inputs="{}",
        **values,
    )
    return report_id


def _insert_budget_window_run(
    connection: Connection, public_api_rows: PublicApiRows, report_id: object
) -> object:
    window_run_id = uuid4()
    insert_row(
        connection,
        "budget_window_runs",
        id=window_run_id,
        report_id=report_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        trigger="initial",
        recalculate=False,
        status="running",
    )
    return window_run_id


def test_budget_windows_hold_one_report_run_per_year(
    connection: Connection, public_api_rows: PublicApiRows
) -> None:
    for refused_values in (
        {"year": 2026, "budget_window_size": 0},
        {"year": 2026, "budget_window_size": 76},
        {"year": 2190, "budget_window_size": 12},
        {"budget_window_size": 3},
        {"year": 2026, "budget_window_size": 3, "household_id": None},
    ):
        values = dict(refused_values)
        if "household_id" in values:
            values["household_id"] = public_api_rows.household_id
        with refused(connection, match="ck_reports_budget_window_size"):
            _insert_report(connection, public_api_rows, **values)
    report_id = _insert_report(
        connection, public_api_rows, year=2026, budget_window_size=3
    )
    other_report_id = _insert_report(connection, public_api_rows, year=2026)
    window_run_id = _insert_budget_window_run(connection, public_api_rows, report_id)
    simulation_id = _insert_simulation(connection, public_api_rows)

    def insert_year(year: int | None, *, of_report: object = report_id) -> None:
        insert_row(
            connection,
            "report_runs",
            id=uuid4(),
            report_id=of_report,
            budget_window_run_id=window_run_id,
            year=year,
            baseline_simulation_run_id=_insert_simulation_run(
                connection, simulation_id, year=year or 2026
            ),
            status="pending",
            trigger="initial",
            **RUN_VERSIONS,
        )

    insert_year(2026)
    insert_year(2027)
    with refused(connection, match="uq_report_runs_budget_window_run_id_year"):
        insert_year(2027)
    with refused(connection, match="ck_report_runs_budget_window_year"):
        insert_year(None)
    with refused(connection, match="foreign key constraint"):
        insert_year(2028, of_report=other_report_id)
    with refused(connection, match="ck_simulation_runs_year"):
        _insert_simulation_run(connection, simulation_id, year=1800)
    # A window run owns its years, as the report owns its runs.
    second_window_run_id = _insert_budget_window_run(
        connection, public_api_rows, report_id
    )
    connection.execute(
        text("DELETE FROM budget_window_runs WHERE id = :id"),
        {"id": window_run_id},
    )
    assert _count(connection, "report_runs", "budget_window_run_id", window_run_id) == 0

    connection.execute(text("DELETE FROM reports WHERE id = :id"), {"id": report_id})
    assert _count(connection, "budget_window_runs", "id", second_window_run_id) == 0
    assert _count(connection, "report_runs", "report_id", report_id) == 0


def test_household_jobs_take_a_valid_year_and_record_when_they_end(
    connection: Connection, public_api_rows: PublicApiRows
) -> None:
    household_job = {
        "country": "us",
        "household_id": public_api_rows.household_id,
        "request_data": "{}",
        "tax_benefit_model_version_id": public_api_rows.version_id,
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
