"""Write simulation-side v2 rows with plain SQL in the integration tests.

The statements run as whichever role the connection acts as, so a test can
check what that role may do. Tests write inside a transaction they roll back.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection

# The package versions a test run records.
RUN_VERSIONS = {"country_package_version": "1.0.0", "policyengine_version": "4.0.0"}


@dataclass(frozen=True)
class PublicApiRows:
    """The Public API's rows a simulation, report or household job names."""

    model_id: UUID
    version_id: UUID
    dataset_id: UUID
    household_id: UUID


def insert_public_api_rows(connection: Connection) -> PublicApiRows:
    """Store a model, one of its versions, a dataset and a US household.

    The simulation tables' foreign keys need them. Run it as the disposable
    database's superuser: the simulation API's roles can't write these tables.
    """
    rows = PublicApiRows(
        model_id=uuid4(), version_id=uuid4(), dataset_id=uuid4(), household_id=uuid4()
    )
    # Model names are unique and at most 32 characters.
    insert_row(
        connection,
        "tax_benefit_models",
        id=rows.model_id,
        name=f"runs-{rows.model_id.hex[:24]}",
    )
    insert_row(
        connection,
        "tax_benefit_model_versions",
        id=rows.version_id,
        model_id=rows.model_id,
        version="1.0.0",
        current_law_id=1,
        metadata_time_periods="[2026]",
    )
    insert_row(
        connection,
        "datasets",
        id=rows.dataset_id,
        name="populace",
        year=2026,
        is_output_dataset=False,
        tax_benefit_model_version_id=rows.version_id,
    )
    insert_row(
        connection,
        "households",
        id=rows.household_id,
        country_id="us",
        household_data="{}",
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return rows


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


def delete_public_api_rows(connection: Connection, rows: PublicApiRows) -> None:
    """Delete what ``insert_public_api_rows`` stored, once nothing names it."""
    for table, row_id in (
        ("households", rows.household_id),
        ("datasets", rows.dataset_id),
        ("tax_benefit_model_versions", rows.version_id),
        ("tax_benefit_models", rows.model_id),
    ):
        connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
