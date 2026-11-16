"""PostgreSQL tests for refreshing the catalog tables' statistics after publication.

PostgreSQL re-collects a table's statistics on its own only after about a tenth
of its rows change. ``parameters`` keeps every published version, so on staging
one release's rows stayed under that share: after 6.17.1 was published on
2026-11-10, the planner estimated 1 parameter row for US 6.17.1 instead of
102,530 and served ``GET /v2/parameter-values?country_id=us&limit=1`` in 43-47
seconds. Every publication now runs ``ANALYZE`` on the catalog tables once it
has committed and pruned; a failed ``ANALYZE`` is recorded in the evidence and
the next publication runs it again. ``ANALYZE`` skips, with only a warning, a
table the role neither owns nor holds ``MAINTAIN`` on, so publication checks
that privilege first and fails before writing anything without it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from policyengine_api.data.v2.catalog.publication import publish_catalog
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.privilege_reconciliation import (
    apply_declared_privileges,
)
from policyengine_api.data.v2.privileges import (
    CATALOG_WRITER_ROLE,
    declared_privileges,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from tests.fixtures.v2_catalog import normalized_catalog

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from sqlalchemy.engine import Engine

REPO = Path(__file__).parents[2]
DISPOSABLE_DATABASE = "policyengine_v2_alembic_test"
UNDEFINED_TABLE_FAILURE = "psycopg.errors.UndefinedTable (SQLSTATE 42P01)"
ANALYZED_TABLES = (
    "datasets",
    "parameter_nodes",
    "parameter_tree_children",
    "parameter_values",
    "parameters",
    "regions",
    "variables",
)


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    url = make_url(database_url)
    if url.database != DISPOSABLE_DATABASE or url.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
    }:
        pytest.fail("catalog publication tests require disposable local Postgres")
    return database_url


@pytest.fixture
def superuser_engine() -> Iterator[Engine]:
    """Upgrade the disposable database and empty its catalog before and after."""
    database_url = _disposable_url()
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
        engine.dispose()


@pytest.fixture
def writer_engine(superuser_engine, v2_engine_as_role) -> Iterator[Engine]:
    engine = v2_engine_as_role(CATALOG_WRITER_ROLE, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


def _database_time(engine: Engine) -> datetime:
    with engine.connect() as connection:
        return connection.execute(text("SELECT clock_timestamp()")).scalar_one()


def _last_manual_analyze(engine: Engine) -> dict[str, datetime | None]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, last_analyze FROM pg_stat_user_tables "
                "WHERE schemaname = 'public' AND relname = ANY(:tables)"
            ),
            {"tables": list(ANALYZED_TABLES)},
        )
        return {row.relname: row.last_analyze for row in rows}


def test_publishing_a_new_version_as_the_catalog_writer_analyzes_the_catalog(
    superuser_engine, writer_engine
) -> None:
    started = _database_time(superuser_engine)

    evidence = publish_catalog(writer_engine, normalized_catalog())
    last_analyze = _last_manual_analyze(superuser_engine)

    assert evidence.catalog_tables_analyzed == ANALYZED_TABLES
    assert evidence.as_dict()["catalog_tables_analyzed"] == list(ANALYZED_TABLES)
    assert sorted(last_analyze) == list(ANALYZED_TABLES)
    assert all(
        analyzed_at is not None and analyzed_at >= started
        for analyzed_at in last_analyze.values()
    ), last_analyze


def test_republishing_an_unchanged_catalog_analyzes_it_again(
    superuser_engine, writer_engine
) -> None:
    """Every run analyzes, so a run after a failed ``ANALYZE`` repeats it."""
    catalog = normalized_catalog()
    publish_catalog(writer_engine, catalog)
    second_started = _database_time(superuser_engine)

    second = publish_catalog(writer_engine, catalog)
    last_analyze = _last_manual_analyze(superuser_engine)

    assert second.catalog_tables_analyzed == ANALYZED_TABLES
    assert second.catalog_statistics_failure is None
    assert all(
        analyzed_at is not None and analyzed_at >= second_started
        for analyzed_at in last_analyze.values()
    ), last_analyze


def test_a_failed_analyze_is_recorded_and_the_publication_kept(
    superuser_engine, writer_engine
) -> None:
    """The database refuses the ``ANALYZE``, and SQLAlchemy wraps its error.

    The evidence names the driver's error and SQLSTATE, as a failed pruning's
    does, not SQLAlchemy's wrapper, which is the same for any database error.
    """

    def analyze_a_missing_table(
        _connection, _cursor, statement, parameters, *_arguments
    ):
        if statement.startswith("ANALYZE"):
            return "ANALYZE public.no_such_catalog_table", parameters
        return statement, parameters

    event.listen(
        writer_engine, "before_cursor_execute", analyze_a_missing_table, retval=True
    )

    evidence = publish_catalog(writer_engine, normalized_catalog())
    with superuser_engine.connect() as connection:
        stored_versions = connection.execute(
            text("SELECT count(*) FROM tax_benefit_model_versions")
        ).scalar_one()

    assert stored_versions > 0
    assert evidence.catalog_tables_analyzed == ()
    assert evidence.catalog_statistics_failure == UNDEFINED_TABLE_FAILURE
    assert evidence.as_dict()["catalog_statistics_failure"] == UNDEFINED_TABLE_FAILURE


@pytest.fixture
def writer_without_maintain(superuser_engine) -> Iterator[str]:
    """Create a role with the catalog writer's declared privileges except MAINTAIN."""
    role = f"policyengine_catalog_test_{uuid4().hex[:12]}"
    writer_tables = declared_privileges("test")[CATALOG_WRITER_ROLE]
    declared = {
        role: {
            table: frozenset(
                privilege for privilege in privileges if privilege != "MAINTAIN"
            )
            for table, privileges in writer_tables.items()
        }
    }
    with superuser_engine.begin() as connection:
        connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        apply_declared_privileges(connection, declared)
    try:
        yield role
    finally:
        with superuser_engine.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{role}"'))
            connection.execute(text(f'DROP ROLE "{role}"'))


def test_a_role_that_cannot_analyze_the_catalog_fails_before_writing(
    superuser_engine, v2_engine_as_role, writer_without_maintain
) -> None:
    engine = v2_engine_as_role(writer_without_maintain, poolclass=NullPool)
    try:
        with pytest.raises(CatalogPublicationError) as raised:
            publish_catalog(engine, normalized_catalog())
    finally:
        engine.dispose()
    with superuser_engine.connect() as connection:
        stored_versions = connection.execute(
            text("SELECT count(*) FROM tax_benefit_model_versions")
        ).scalar_one()

    assert "MAINTAIN" in str(raised.value)
    assert "parameters" in str(raised.value)
    assert stored_versions == 0
