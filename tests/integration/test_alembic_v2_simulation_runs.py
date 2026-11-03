"""Check the simulation runs revision against disposable Postgres.

The revision adds simulation runs and the table naming the simulation runs a
report run combines, keys every result table by run, and gives household jobs
one household, one year and one policy. It changes no other table, so the
previous Public API revision, whose roles can't read or write any table it
changes, keeps working while it is deployed.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from policyengine_api.constants import REPO
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

SIMULATION_RUNS_PREVIOUS_REVISION = "c614b6bcccfc"
NEW_TABLES = frozenset({"simulation_runs", "report_run_simulation_runs"})
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
        "simulations",
    }
)
SHA256_HEX = "a" * 64


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


def test_the_revision_adds_two_tables_and_changes_only_simulation_side_tables(
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


@contextmanager
def _refused(connection: Connection) -> Iterator[None]:
    """Expect the statement inside to violate a constraint, then roll it back."""
    savepoint = connection.begin_nested()
    with pytest.raises(IntegrityError):
        yield
    savepoint.rollback()


def _insert(connection: Connection, table: str, **values: object) -> None:
    columns = ", ".join(values)
    placeholders = ", ".join(f":{column}" for column in values)
    connection.execute(
        text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"), values
    )


def _insert_simulation_run(
    connection: Connection,
    simulation_id: object,
    version_id: object,
    *,
    status: str = "pending",
    **values: object,
) -> object:
    run_id = uuid4()
    _insert(
        connection,
        "simulation_runs",
        id=run_id,
        simulation_id=simulation_id,
        tax_benefit_model_version_id=version_id,
        country_package_version="1.0.0",
        policyengine_version="4.0.0",
        status=status,
        **values,
    )
    return run_id


def test_run_tables_enforce_completion_output_and_uniqueness(
    config: Config, engine: Engine
) -> None:
    command.upgrade(config, "head")
    model_id, version_id, dataset_id = uuid4(), uuid4(), uuid4()
    simulation_id, report_id, report_run_id = uuid4(), uuid4(), uuid4()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _insert(
                connection,
                "tax_benefit_models",
                id=model_id,
                name=f"runs-{model_id.hex[:8]}",
            )
            connection.execute(
                text(
                    "INSERT INTO tax_benefit_model_versions "
                    "(id, model_id, version, current_law_id, metadata_time_periods) "
                    "VALUES (:id, :model_id, '1.0.0', 1, '[2026]')"
                ),
                {"id": version_id, "model_id": model_id},
            )
            _insert(
                connection,
                "datasets",
                id=dataset_id,
                name="populace",
                year=2026,
                is_output_dataset=False,
                tax_benefit_model_version_id=version_id,
            )
            _insert(
                connection,
                "simulations",
                id=simulation_id,
                simulation_type="economy",
                dataset_id=dataset_id,
                tax_benefit_model_version_id=version_id,
                year=2026,
            )
            baseline_run_id = _insert_simulation_run(
                connection, simulation_id, version_id
            )
            reform_run_id = _insert_simulation_run(
                connection,
                simulation_id,
                version_id,
                status="succeeded",
                completed_at="2026-11-04T00:00:00Z",
                output_uri="gs://bucket/run.parquet",
                output_sha256=SHA256_HEX,
            )

            with _refused(connection):
                connection.execute(
                    text(
                        "UPDATE simulation_runs SET status = 'succeeded' WHERE id = :id"
                    ),
                    {"id": baseline_run_id},
                )
            with _refused(connection):
                _insert_simulation_run(
                    connection,
                    simulation_id,
                    version_id,
                    output_uri="gs://bucket/run.parquet",
                )
            with _refused(connection):
                _insert_simulation_run(
                    connection,
                    simulation_id,
                    version_id,
                    output_uri="gs://bucket/run.parquet",
                    output_sha256="short",
                )

            _insert(
                connection,
                "reports",
                id=report_id,
                label="Report",
                country="us",
                tax_benefit_model_id=model_id,
                inputs="{}",
            )
            _insert(
                connection,
                "report_runs",
                id=report_run_id,
                report_id=report_id,
                country_package_version="1.0.0",
                policyengine_version="4.0.0",
                status="running",
                trigger="initial",
            )
            _insert(
                connection,
                "report_run_simulation_runs",
                id=uuid4(),
                report_run_id=report_run_id,
                simulation_run_id=baseline_run_id,
                role="baseline",
            )
            with _refused(connection):
                _insert(
                    connection,
                    "report_run_simulation_runs",
                    id=uuid4(),
                    report_run_id=report_run_id,
                    simulation_run_id=baseline_run_id,
                    role="baseline",
                )
            with _refused(connection):
                _insert(
                    connection,
                    "budget_summary",
                    id=uuid4(),
                    report_run_id=report_run_id,
                    baseline_simulation_run_id=baseline_run_id,
                    reform_simulation_run_id=uuid4(),
                    variable_name="household_net_income",
                    entity="household",
                )

            _insert(
                connection,
                "poverty",
                id=uuid4(),
                simulation_run_id=reform_run_id,
                poverty_type="poverty",
                entity="person",
            )
            with _refused(connection):
                _insert(
                    connection,
                    "poverty",
                    id=uuid4(),
                    simulation_run_id=reform_run_id,
                    poverty_type="poverty",
                    entity="person",
                )

            household_job = {
                "country": "us",
                "household_id": uuid4(),
                "request_data": "{}",
                "tax_benefit_model_version_id": version_id,
                "country_package_version": "1.0.0",
                "policyengine_version": "4.0.0",
            }
            _insert(
                connection,
                "household_jobs",
                id=uuid4(),
                year=2026,
                status="pending",
                **household_job,
            )
            with _refused(connection):
                _insert(
                    connection,
                    "household_jobs",
                    id=uuid4(),
                    year=1800,
                    status="pending",
                    **household_job,
                )
            with _refused(connection):
                _insert(
                    connection,
                    "household_jobs",
                    id=uuid4(),
                    year=2026,
                    status="failed",
                    **household_job,
                )

            connection.execute(
                text("DELETE FROM report_runs WHERE id = :id"), {"id": report_run_id}
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM report_run_simulation_runs")
                ).scalar_one()
                == 0
            )
            connection.execute(
                text("DELETE FROM simulations WHERE id = :id"), {"id": simulation_id}
            )
            remaining_runs = connection.execute(
                text("SELECT count(*) FROM simulation_runs")
            ).scalar_one()
            remaining_poverty = connection.execute(
                text("SELECT count(*) FROM poverty")
            ).scalar_one()
            assert (remaining_runs, remaining_poverty) == (0, 0)
        finally:
            transaction.rollback()
