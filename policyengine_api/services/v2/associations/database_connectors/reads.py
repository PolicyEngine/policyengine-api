"""Database reads shared by every user-owned association table."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.services.v2.associations.types import AssociationTable


def read_association_ids_by_client_ref(
    session: Session,
    table: type[AssociationTable],
    *,
    user_id: UUID,
    client_refs: Collection[str],
    country_id: str | None,
) -> dict[str, UUID]:
    """Return the owner's association IDs keyed by client_ref.

    ``country_id`` restricts the match to one country; ``None`` matches every
    country, because ``client_ref`` is unique per user across countries.
    """

    if not client_refs:
        return {}
    statement = select(table.client_ref, table.id).where(
        table.user_id == user_id,
        col(table.client_ref).in_(sorted(set(client_refs))),
    )
    if country_id is not None:
        statement = statement.where(table.country_id == country_id)
    return {
        client_ref: association_id
        for client_ref, association_id in session.exec(statement).all()
        if client_ref is not None
    }
