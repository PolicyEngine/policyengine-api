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

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import REGCLASS

from policyengine_api.data.v2.catalog import publication as publication_module
from policyengine_api.data.v2.catalog import publication_statistics
from policyengine_api.data.v2.catalog.publication import publish_catalog
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.models import TaxBenefitModelVersion
from policyengine_api.data.v2.privilege_reconciliation import (
    apply_declared_privileges,
)
from policyengine_api.data.v2.privileges import (
    CATALOG_WRITER_ROLE,
    declared_privileges,
)
from tests.fixtures.database_sessions import create_role, drop_role
from tests.fixtures.v2_catalog import normalized_catalog
from tests.integration.catalog_publication_support import emptied_catalog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from datetime import datetime

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

UNDEFINED_TABLE_FAILURE = "psycopg.errors.UndefinedTable (SQLSTATE 42P01)"
ANALYZED_TABLES = (
    "datasets",
    "dynamic_parameter_values",
    "dynamic_parameters",
    "parameter_nodes",
    "parameter_tree_children",
    "parameter_values",
    "parameters",
    "regions",
    "variables",
)


@pytest.fixture
def superuser_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Upgrade the disposable database and empty its catalog before and after."""
    with emptied_catalog(v2_owner_sessions) as sessions:
        yield sessions


@pytest.fixture
def writer_sessions(
    superuser_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> sessionmaker[Session]:
    return v2_sessions_as_role(CATALOG_WRITER_ROLE)


def _database_time(sessions: sessionmaker[Session]) -> datetime:
    with sessions() as session:
        moment: datetime = session.execute(select(func.clock_timestamp())).scalar_one()
    return moment


def _last_manual_analyze(
    sessions: sessionmaker[Session],
) -> dict[str, datetime | None]:
    """Return when each catalog table was last analyzed by an ``ANALYZE``.

    ``pg_stat_get_last_analyze_time`` is what ``pg_stat_user_tables`` reports
    as ``last_analyze``.
    """
    with sessions() as session:
        return {
            table: session.execute(
                select(
                    func.pg_stat_get_last_analyze_time(
                        cast(f"public.{table}", REGCLASS)
                    )
                )
            ).scalar_one()
            for table in ANALYZED_TABLES
        }


def _stored_version_count(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        count: int = session.execute(
            select(func.count()).select_from(TaxBenefitModelVersion)
        ).scalar_one()
    return count


def test_publishing_a_new_version_as_the_catalog_writer_analyzes_the_catalog(
    superuser_sessions: sessionmaker[Session], writer_sessions: sessionmaker[Session]
) -> None:
    started = _database_time(superuser_sessions)

    evidence = publish_catalog(writer_sessions, normalized_catalog())
    last_analyze = _last_manual_analyze(superuser_sessions)

    assert evidence.catalog_tables_analyzed == ANALYZED_TABLES
    assert evidence.as_dict()["catalog_tables_analyzed"] == list(ANALYZED_TABLES)
    assert sorted(last_analyze) == list(ANALYZED_TABLES)
    assert all(
        analyzed_at is not None and analyzed_at >= started
        for analyzed_at in last_analyze.values()
    ), last_analyze


def test_republishing_an_unchanged_catalog_analyzes_it_again(
    superuser_sessions: sessionmaker[Session], writer_sessions: sessionmaker[Session]
) -> None:
    """Every run analyzes, so a run after a failed ``ANALYZE`` repeats it."""
    catalog = normalized_catalog()
    publish_catalog(writer_sessions, catalog)
    second_started = _database_time(superuser_sessions)

    second = publish_catalog(writer_sessions, catalog)
    last_analyze = _last_manual_analyze(superuser_sessions)

    assert second.catalog_tables_analyzed == ANALYZED_TABLES
    assert second.catalog_statistics_failure is None
    assert all(
        analyzed_at is not None and analyzed_at >= second_started
        for analyzed_at in last_analyze.values()
    ), last_analyze


def test_a_failed_analyze_is_recorded_and_the_publication_kept(
    superuser_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The database refuses the ``ANALYZE``, and SQLAlchemy wraps its error.

    The evidence names the driver's error and SQLSTATE, as a failed pruning's
    does, not SQLAlchemy's wrapper, which is the same for any database error.
    The ``ANALYZE`` names a table that doesn't exist, once publication has
    checked the privileges on the real ones.
    """
    analyze_catalog_tables = publication_statistics.analyze_catalog_tables

    def analyze_a_missing_table(sessions: sessionmaker[Session]):
        monkeypatch.setattr(
            publication_statistics,
            "CATALOG_STATISTICS_TABLES",
            ("no_such_catalog_table",),
        )
        return analyze_catalog_tables(sessions)

    monkeypatch.setattr(
        publication_module, "analyze_catalog_tables", analyze_a_missing_table
    )

    evidence = publish_catalog(writer_sessions, normalized_catalog())
    stored_versions = _stored_version_count(superuser_sessions)

    assert stored_versions > 0
    assert evidence.catalog_tables_analyzed == ()
    assert evidence.catalog_statistics_failure == UNDEFINED_TABLE_FAILURE
    assert evidence.as_dict()["catalog_statistics_failure"] == UNDEFINED_TABLE_FAILURE


@pytest.fixture
def writer_without_maintain(
    superuser_sessions: sessionmaker[Session],
) -> Iterator[str]:
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
    with superuser_sessions.begin() as session:
        create_role(session, role)
        apply_declared_privileges(session, declared)
    try:
        yield role
    finally:
        with superuser_sessions.begin() as session:
            drop_role(session, role)


def test_a_role_that_cannot_analyze_the_catalog_fails_before_writing(
    superuser_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    writer_without_maintain: str,
) -> None:
    with pytest.raises(CatalogPublicationError) as raised:
        publish_catalog(
            v2_sessions_as_role(writer_without_maintain), normalized_catalog()
        )
    stored_versions = _stored_version_count(superuser_sessions)

    assert "MAINTAIN" in str(raised.value)
    assert "parameters" in str(raised.value)
    assert stored_versions == 0
