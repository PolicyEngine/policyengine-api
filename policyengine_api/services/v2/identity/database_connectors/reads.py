"""Database selections used by v2 identity resolution."""

from __future__ import annotations

from sqlmodel import Session, select

from policyengine_api.data.v2.models import UserIdentity


def read_user_identity(
    session: Session,
    *,
    issuer: str,
    subject: str,
) -> UserIdentity | None:
    return session.exec(
        select(UserIdentity).where(
            UserIdentity.issuer == issuer,
            UserIdentity.subject == subject,
        )
    ).one_or_none()
