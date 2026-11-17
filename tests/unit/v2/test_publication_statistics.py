"""How the ANALYZE after a catalog publication reports a failure.

The PostgreSQL tests (``tests/integration/test_v2_catalog_statistics.py``) cover
a database error, which is named by the driver's class and SQLSTATE. Any other
failure is named by its class alone, never its message.
"""

from __future__ import annotations

from policyengine_api.data.v2.catalog.publication_statistics import (
    analyze_catalog_tables,
)


class EngineThatCannotConnect:
    """Stands in for an engine whose connection fails before any statement."""

    def begin(self) -> None:
        msg = "postgresql://writer:hunter2@db.example.internal refused the connection"
        raise RuntimeError(msg)


def test_a_failure_that_is_not_a_database_error_is_named_by_its_class() -> None:
    refresh = analyze_catalog_tables(EngineThatCannotConnect())

    assert refresh.analyzed == ()
    assert refresh.failure_type == "builtins.RuntimeError"
