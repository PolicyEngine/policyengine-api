"""Database reads for signed-in v2 accounts."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import User, UserIdentity


def read_account_user(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def read_identity_subjects(
    session: Session,
    *,
    user_id: UUID,
    issuer: str,
) -> list[str]:
    return list(
        session.exec(
            select(UserIdentity.subject)
            .where(UserIdentity.user_id == user_id, UserIdentity.issuer == issuer)
            .order_by(col(UserIdentity.created_at), col(UserIdentity.id))
        ).all()
    )
