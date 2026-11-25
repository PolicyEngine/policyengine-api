"""Proof fixture: rows written with handwritten SQL on a Core Connection.

The rule must reject it. ``insert_row``, ``refused`` and ``delete_rows`` are
the row helpers of ``tests/integration/simulation_rows.py`` as of d6693ad36:
they build INSERT and DELETE statements from strings and run them on a
``Connection``, inside a savepoint the Connection opens. ``STAGE_CATALOG_MODELS``
is the Core table ``tests/unit/v2/test_catalog_publication.py`` declares for
catalog publication's COPY (added in f83b4b5fb), which no mapped class maps.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from uuid import UUID

    from sqlalchemy import Connection

STAGE_CATALOG_MODELS = sa.Table(
    "stage_catalog_models",
    sa.MetaData(),
    sa.Column("id", sa.Integer),
    sa.Column("name", sa.Text),
)


def insert_row(connection: Connection, table: str, **values: object) -> None:
    """Insert one row of the named columns into ``table``."""
    columns = ", ".join(values)
    placeholders = ", ".join(f":{column}" for column in values)
    connection.execute(
        text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"),  # noqa: S608  # the handwritten SQL the rule rejects
        values,
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


def delete_rows(connection: Connection, rows: Iterable[tuple[str, UUID]]) -> None:
    """Delete each row by its table's name and its id, in the order given."""
    for table, row_id in rows:
        connection.execute(
            text(f"DELETE FROM {table} WHERE id = :id"),  # noqa: S608  # the handwritten SQL the rule rejects
            {"id": row_id},
        )
