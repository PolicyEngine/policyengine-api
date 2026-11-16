"""Refresh the planner statistics of the catalog tables after a publication.

PostgreSQL's autovacuum analyzes a table again only after about a tenth of its
rows have changed since the last time. ``parameters`` and ``parameter_values``
keep every published catalog version, so as they grow one release's rows stay
under that share. On staging, after 6.17.1 was published on 2026-11-10, the
planner estimated 1 parameter row for US 6.17.1 instead of 102,530, and
``GET /v2/parameter-values?country_id=us&limit=1`` took 43 to 47 seconds until
``ANALYZE parameters`` brought it to 4.1 ms.

So publication runs one ``ANALYZE`` over the catalog tables it writes after a
run that publishes, restores or prunes a catalog version
(``analyze_catalog_tables``). ``ANALYZE`` needs the table's owner or the
``MAINTAIN`` privilege, and PostgreSQL skips any other table with only a
warning. The migration role owns every table, so the manifest declares
``MAINTAIN`` for the catalog writer on these tables, and publication checks
that its role holds it before it writes anything
(``require_analyze_privilege``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection, Engine

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

_HAS_MAINTAIN = sa.text(
    "SELECT has_table_privilege(current_user, :qualified_table, 'MAINTAIN')"
)


def require_analyze_privilege(connection: Connection) -> None:
    """Raise unless the connection's role may ``ANALYZE`` every catalog table.

    An owner holds every privilege, so ``has_table_privilege`` answers for
    ownership and a ``MAINTAIN`` grant alike.
    """
    missing = [
        table
        for table in CATALOG_STATISTICS_TABLES
        if not connection.execute(
            _HAS_MAINTAIN, {"qualified_table": f"public.{table}"}
        ).scalar_one()
    ]
    if missing:
        msg = (
            "the publication role lacks MAINTAIN on "
            + ", ".join(missing)
            + ", so ANALYZE would skip them with only a warning; nothing was "
            "published"
        )
        raise CatalogPublicationError(msg)


def analyze_catalog_tables(engine: Engine) -> tuple[str, ...]:
    """Run one ``ANALYZE`` over the catalog tables and return their names."""
    tables = ", ".join(f"public.{table}" for table in CATALOG_STATISTICS_TABLES)
    with engine.begin() as connection:
        connection.execute(sa.text(f"ANALYZE {tables}"))
    return CATALOG_STATISTICS_TABLES
