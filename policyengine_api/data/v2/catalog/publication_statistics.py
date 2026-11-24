"""Refresh the planner statistics of the catalog tables after a publication.

PostgreSQL's autovacuum analyzes a table again only after about a tenth of its
rows have changed since the last time. ``parameters`` and ``parameter_values``
keep every published catalog version, so as they grow one release's rows stay
under that share. On staging, after 6.17.1 was published on 2026-11-10, the
planner estimated 1 parameter row for US 6.17.1 instead of 102,530, and
``GET /v2/parameter-values?country_id=us&limit=1`` took 43 to 47 seconds until
``ANALYZE parameters`` brought it to 4.1 ms.

So every publication runs one ``ANALYZE`` over the catalog tables it writes,
once it has committed and pruned (``analyze_catalog_tables``). It takes a few
seconds and blocks no reads. Running it every time, rather than only after a
run that changed a version, means a failed ``ANALYZE``, which is recorded in
the evidence by its error class like a failed pruning, is repeated by the
next publication instead of leaving the statistics stale.

``ANALYZE`` needs the table's owner or the ``MAINTAIN`` privilege, and
PostgreSQL skips any other table with only a warning. The migration role owns
every table, so the manifest declares ``MAINTAIN`` for the catalog writer on
these tables, and publication checks that its role holds it before it writes
anything (``require_analyze_privilege``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

CATALOG_STATISTICS_TABLES: Final = (
    "datasets",
    "parameter_nodes",
    "parameter_tree_children",
    "parameter_values",
    "parameters",
    "regions",
    "variables",
)
"""The catalog tables publication analyzes, in name order."""


def _has_maintain(qualified_table: str) -> sa.Select[tuple[bool]]:
    """Select whether the current role holds ``MAINTAIN`` on the table."""
    return sa.select(
        sa.func.has_table_privilege(
            sa.func.current_user(), qualified_table, "MAINTAIN", type_=sa.Boolean
        )
    )


def require_analyze_privilege(session: Session) -> None:
    """Raise unless the session's role may ``ANALYZE`` every catalog table.

    An owner holds every privilege, so ``has_table_privilege`` answers for
    ownership and a ``MAINTAIN`` grant alike.
    """
    missing = [
        table
        for table in CATALOG_STATISTICS_TABLES
        if not session.execute(_has_maintain(f"public.{table}")).scalar_one()
    ]
    if missing:
        msg = (
            "the publication role lacks MAINTAIN on "
            + ", ".join(missing)
            + ", so ANALYZE would skip them with only a warning; nothing was "
            "published"
        )
        raise CatalogPublicationError(msg)


@dataclass(frozen=True, slots=True)
class CatalogStatisticsRefresh:
    """What the ``ANALYZE`` after a publication did.

    ``analyzed`` names the tables, empty when it failed. ``failure_type`` then
    names the failure without its message: for a database error, the class of
    the error the driver raised and its SQLSTATE, as a failed pruning reports
    it, since SQLAlchemy's own class is the same for every database error.
    """

    analyzed: tuple[str, ...]
    failure_type: str | None = None


def analyze_catalog_tables(sessions: sessionmaker[Session]) -> CatalogStatisticsRefresh:
    """Run one ``ANALYZE`` over the catalog tables; a failure is returned, not raised.

    It runs in a transaction of its own, after the publication committed, so a
    failure, of any kind, never undoes it; the next publication analyzes again.
    ``ANALYZE`` has no ORM form, so it is SQL text (a rule exception).
    """
    tables = ", ".join(f"public.{table}" for table in CATALOG_STATISTICS_TABLES)
    try:
        with sessions.begin() as session:
            session.execute(sa.text(f"ANALYZE {tables}"))
    except Exception as error:  # noqa: BLE001  # the publication has committed; the next one analyzes again
        return CatalogStatisticsRefresh(analyzed=(), failure_type=_failure(error))
    return CatalogStatisticsRefresh(analyzed=CATALOG_STATISTICS_TABLES)


def _failure(error: Exception) -> str:
    """Name a failure by its class and a database error's SQLSTATE, not its message."""
    driver_error = getattr(error, "orig", None)
    reported = (
        driver_error
        if isinstance(error, SQLAlchemyError) and isinstance(driver_error, Exception)
        else error
    )
    reported_class = type(reported)
    name = f"{reported_class.__module__}.{reported_class.__qualname__}"
    sqlstate = getattr(reported, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate:
        return f"{name} (SQLSTATE {sqlstate})"
    return name
