"""Write simulation-side v2 rows through a Session in the integration tests.

The statements run as whichever role the Session acts as, so a test can
check what that role may do. Tests write inside a transaction they roll back.
``add_row`` writes one row of a mapped class, and ``refused`` expects the
statements inside it to fail.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Dataset,
    Household,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection
    from sqlalchemy.orm import Session

# The package versions a test run records.
RUN_VERSIONS = {"country_package_version": "1.0.0", "policyengine_version": "4.0.0"}


@dataclass(frozen=True)
class PublicApiRows:
    """API v1's rows a simulation, report or household job names."""

    model_id: UUID
    version_id: UUID
    dataset_id: UUID
    household_id: UUID


def add_row(session: Session, model: type[Any], **values: object) -> None:
    """Insert one row of the mapped class ``model`` with the given columns.

    Columns not given take the model's defaults, then the database's.
    """
    session.execute(insert(model).values(**values))


def insert_public_api_rows(session: Session) -> PublicApiRows:
    """Store a model, one of its versions, a dataset and a US household.

    The simulation tables' foreign keys need them. Run it as the disposable
    database's owner: the simulation API's roles can't write these tables.
    """
    rows = PublicApiRows(
        model_id=uuid4(), version_id=uuid4(), dataset_id=uuid4(), household_id=uuid4()
    )
    # Model names are unique and at most 32 characters.
    add_row(
        session,
        TaxBenefitModel,
        id=rows.model_id,
        name=f"runs-{rows.model_id.hex[:24]}",
    )
    add_row(
        session,
        TaxBenefitModelVersion,
        id=rows.version_id,
        model_id=rows.model_id,
        version="1.0.0",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    add_row(
        session,
        Dataset,
        id=rows.dataset_id,
        name="populace",
        year=2026,
        is_output_dataset=False,
        tax_benefit_model_version_id=rows.version_id,
    )
    add_row(
        session,
        Household,
        id=rows.household_id,
        country_id="us",
        household_data={},
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return rows


def insert_row(connection: Connection, table: str, **values: object) -> None:
    """Insert one row of the named columns into ``table``, as handwritten SQL.

    Only for the callers that still pass a Connection and a table's name;
    rule api.data.orm-only reports it. Use ``add_row``.
    """
    columns = ", ".join(values)
    placeholders = ", ".join(f":{column}" for column in values)
    connection.execute(
        text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"), values
    )


@contextmanager
def refused(
    session: Session,
    error: type[Exception] = IntegrityError,
    *,
    match: str | None = None,
) -> Iterator[None]:
    """Expect the statements inside to fail with ``error``, then roll them back.

    They run in a savepoint (``Session.begin_nested``), so the test's
    transaction goes on.
    """
    with pytest.raises(error, match=match), session.begin_nested():
        yield


def delete_public_api_rows(session: Session, rows: PublicApiRows) -> None:
    """Delete what ``insert_public_api_rows`` stored, once nothing names it."""
    session.execute(delete(Household).where(col(Household.id) == rows.household_id))
    session.execute(delete(Dataset).where(col(Dataset.id) == rows.dataset_id))
    session.execute(
        delete(TaxBenefitModelVersion).where(
            col(TaxBenefitModelVersion.id) == rows.version_id
        )
    )
    session.execute(
        delete(TaxBenefitModel).where(col(TaxBenefitModel.id) == rows.model_id)
    )
