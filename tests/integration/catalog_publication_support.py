"""Shared setup and reads for the catalog publication integration tests.

``emptied_catalog`` brings the disposable v2 database to the Alembic head and
empties its catalog before and after a test. ``row_counts`` and
``stored_identifiers`` read tables through their mapped classes, so a test can
check that a publication added, kept or removed exactly the rows it should.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)
from tests.fixtures.database_sessions import truncate

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

REPO = Path(__file__).parents[2]
# The catalog tables publication writes, by name, with their mapped classes.
CATALOG_MODELS: dict[str, Any] = {
    "tax_benefit_models": TaxBenefitModel,
    "tax_benefit_model_versions": TaxBenefitModelVersion,
    "variables": Variable,
    "parameter_nodes": ParameterNode,
    "parameters": Parameter,
    "parameter_values": ParameterValue,
    "datasets": Dataset,
    "regions": Region,
}


@contextmanager
def emptied_catalog(
    sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Yield ``sessions`` on a v2 database at the Alembic head with no catalog.

    The catalog is emptied again on exit. Policies and dynamics name a model, so
    the truncation removes them too, with every row that names a catalog row.
    """
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    with sessions.begin() as session:
        truncate(session, TaxBenefitModel)
    try:
        yield sessions
    finally:
        with sessions.begin() as session:
            truncate(session, TaxBenefitModel)


def row_counts(
    sessions: sessionmaker[Session], models: Mapping[str, Any]
) -> dict[str, int]:
    """Return the number of rows of each table, by the name ``models`` gives it."""
    with sessions() as session:
        return {
            table_name: session.execute(
                select(func.count()).select_from(model)
            ).scalar_one()
            for table_name, model in models.items()
        }


def stored_identifiers(
    sessions: sessionmaker[Session], models: Mapping[str, Any] = CATALOG_MODELS
) -> dict[str, tuple[str, ...]]:
    """Return every row ID of each table, in order, by the name ``models`` gives it."""
    with sessions() as session:
        return {
            table_name: tuple(
                str(row_id)
                for row_id in session.scalars(
                    select(col(model.id)).order_by(col(model.id))
                )
            )
            for table_name, model in models.items()
        }
