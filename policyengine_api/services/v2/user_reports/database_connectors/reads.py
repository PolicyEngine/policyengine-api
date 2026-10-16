"""Database reads for v2 user-report associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import UserPolicy, UserReportAssociation

if TYPE_CHECKING:
    from uuid import UUID


def read_owned_user_report_row(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserReportAssociation | None:
    return session.exec(
        select(UserReportAssociation).where(
            UserReportAssociation.id == association_id,
            UserReportAssociation.country_id == country_id,
            UserReportAssociation.user_id == user_id,
        )
    ).one_or_none()


def read_user_report_row(
    session: Session,
    *,
    country_id: str,
    association_id: UUID,
) -> UserReportAssociation | None:
    """Read a row whoever owns it: a saved report's ID is its shareable link."""

    return session.exec(
        select(UserReportAssociation).where(
            UserReportAssociation.id == association_id,
            UserReportAssociation.country_id == country_id,
        )
    ).one_or_none()


def read_user_report_rows(
    session: Session,
    *,
    country_id: str,
    user_id: UUID,
    legacy_report_id: int | None,
    offset: int,
    limit: int,
) -> list[UserReportAssociation]:
    statement = select(UserReportAssociation).where(
        UserReportAssociation.country_id == country_id,
        UserReportAssociation.user_id == user_id,
    )
    if legacy_report_id is not None:
        statement = statement.where(
            UserReportAssociation.legacy_report_id == legacy_report_id
        )
    return list(
        session.exec(
            statement.order_by(
                col(UserReportAssociation.created_at),
                col(UserReportAssociation.id),
            )
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )


def read_all_user_report_rows(
    session: Session, *, user_id: UUID
) -> list[UserReportAssociation]:
    return list(
        session.exec(
            select(UserReportAssociation)
            .where(UserReportAssociation.user_id == user_id)
            .order_by(
                col(UserReportAssociation.created_at),
                col(UserReportAssociation.id),
            )
        ).all()
    )


def read_owned_user_policy_row(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    user_policy_id: UUID,
) -> UserPolicy | None:
    return session.exec(
        select(UserPolicy).where(
            UserPolicy.id == user_policy_id,
            UserPolicy.user_id == user_id,
            UserPolicy.country_id == country_id,
        )
    ).one_or_none()


def read_owned_user_policy_exists(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    user_policy_id: UUID,
) -> bool:
    return (
        session.exec(
            select(UserPolicy.id).where(
                UserPolicy.id == user_policy_id,
                UserPolicy.user_id == user_id,
                UserPolicy.country_id == country_id,
            )
        ).one_or_none()
        is not None
    )
