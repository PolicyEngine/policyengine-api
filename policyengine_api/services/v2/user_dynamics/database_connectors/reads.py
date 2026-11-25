"""Database selections used by the operations on users' saved dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Dynamic, UserDynamic

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.user_dynamics.types import UserDynamicListing


def read_dynamic_for_association(session: Session, dynamic_id: UUID) -> Dynamic | None:
    """Return the dynamic with this id in any country, or None."""
    return session.exec(select(Dynamic).where(Dynamic.id == dynamic_id)).one_or_none()


def read_owned_user_dynamic_row(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserDynamic | None:
    """Return the user's saved dynamic with this id in this country, or None."""
    return session.exec(
        select(UserDynamic).where(
            UserDynamic.id == association_id,
            UserDynamic.country_id == country_id,
            UserDynamic.user_id == user_id,
        )
    ).one_or_none()


def read_user_dynamic_rows(
    session: Session, listing: UserDynamicListing
) -> list[UserDynamic]:
    """Return up to ``limit + 1`` of a user's saved dynamics in creation order.

    With the listing's ``dynamic_id``, only those naming that dynamic are
    returned. The extra row lets the caller report whether another page exists.
    """
    statement = select(UserDynamic).where(
        UserDynamic.country_id == listing.country_id,
        UserDynamic.user_id == listing.user_id,
    )
    if listing.dynamic_id is not None:
        statement = statement.where(UserDynamic.dynamic_id == listing.dynamic_id)
    return list(
        session.exec(
            statement.order_by(col(UserDynamic.created_at), col(UserDynamic.id))
            .offset(listing.offset)
            .limit(listing.limit + 1)
        ).all()
    )


def read_all_user_dynamic_rows(session: Session, *, user_id: UUID) -> list[UserDynamic]:
    """Return every saved dynamic the user owns, in any country, in creation order."""
    return list(
        session.exec(
            select(UserDynamic)
            .where(UserDynamic.user_id == user_id)
            .order_by(col(UserDynamic.created_at), col(UserDynamic.id))
        ).all()
    )
