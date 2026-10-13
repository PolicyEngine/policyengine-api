"""Database inserts shared by every user-owned association table."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.services.v2.associations.types import AssociationTable


def import_association(
    session: Session,
    table: type[AssociationTable],
    values: Mapping[str, object],
) -> UUID | None:
    """Insert one imported association unless its owner already uses its client_ref.

    Returns the new ID, or ``None`` when ``UNIQUE(user_id, client_ref)`` already
    holds a row.
    """

    return session.execute(
        insert(table)
        .values(**values)
        .on_conflict_do_nothing(constraint=f"uq_{table.__tablename__}_user_client_ref")
        .returning(col(table.id))
    ).scalar_one_or_none()
