"""Proof fixture: rows written through an ORM Session on mapped classes.

The rule must accept it. It is ``bad_simulation_rows.py`` written as the rule
asks: ``add_row`` adds a row of a mapped class, ``refused`` runs the statements
inside it in a savepoint the Session opens, and ``delete_rows`` deletes the v2
rows with ``delete(Model)``. The staging table is a mapped class on a
declarative base of its own, so it stays out of the v2 metadata.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Integer, Text, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from policyengine_api.data.v2.models import (
    Dataset,
    Household,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from sqlalchemy.orm import Session


class StagingBase(DeclarativeBase):
    """The staging tables' declarative base, apart from the v2 metadata."""


class StageCatalogModel(StagingBase):
    """One staged catalog model."""

    __tablename__ = "stage_catalog_models"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)


def add_row(session: Session, model: type[object], **values: object) -> None:
    """Add one row of the mapped class ``model`` and send it to the database."""
    session.add(model(**values))
    session.flush()


@contextmanager
def refused(
    session: Session,
    error: type[Exception] = IntegrityError,
    *,
    match: str | None = None,
) -> Iterator[None]:
    """Expect the statements inside to fail with ``error``, then roll them back."""
    with pytest.raises(error, match=match), session.begin_nested():
        yield


def delete_rows(
    session: Session,
    *,
    household_id: UUID,
    dataset_id: UUID,
    version_id: UUID,
    model_id: UUID,
) -> None:
    """Delete a household, a dataset, a model version and its model, in that order."""
    session.execute(delete(Household).where(Household.id == household_id))
    session.execute(delete(Dataset).where(Dataset.id == dataset_id))
    session.execute(
        delete(TaxBenefitModelVersion).where(TaxBenefitModelVersion.id == version_id)
    )
    session.execute(delete(TaxBenefitModel).where(TaxBenefitModel.id == model_id))
