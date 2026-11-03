"""Write simulation-side v2 rows with plain SQL in the integration tests.

The statements run as whichever role the connection acts as, so a test can
check what that role may do. Tests write inside a transaction they roll back.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection

# The package versions a test run records.
RUN_VERSIONS = {"country_package_version": "1.0.0", "policyengine_version": "4.0.0"}


def insert_row(connection: Connection, table: str, **values: object) -> None:
    """Insert one row of the named columns into ``table``."""
    columns = ", ".join(values)
    placeholders = ", ".join(f":{column}" for column in values)
    connection.execute(
        text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"), values
    )


@contextmanager
def refused(
    connection: Connection,
    error: type[Exception] = IntegrityError,
    *,
    match: str | None = None,
) -> Iterator[None]:
    """Expect the statements inside to fail with ``error``, then roll them back."""
    savepoint = connection.begin_nested()
    with pytest.raises(error, match=match):
        yield
    savepoint.rollback()
