"""Database reads for v2 user-report associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import UserPolicy, UserReportAssociation

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.user_reports.types import UserReportListing


def read_owned_user_report_row(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
    lock: bool = False,
) -> UserReportAssociation | None:
    """Return the user's association with this id in this country, or None.

    With ``lock``, the row is selected FOR UPDATE, so updates of one saved
    report take turns and each sees the row as the one before it left it.
    """
    statement = select(UserReportAssociation).where(
        UserReportAssociation.id == association_id,
        UserReportAssociation.country_id == country_id,
        UserReportAssociation.user_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


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
    listing: UserReportListing,
) -> list[UserReportAssociation]:
    """Return up to ``limit + 1`` of a user's associations in creation order.

    With the listing's ``legacy_report_id``, only associations to that v1 report
    output are returned. The extra row lets the caller report whether another
    page exists.
    """
    statement = select(UserReportAssociation).where(
        UserReportAssociation.country_id == listing.country_id,
        UserReportAssociation.user_id == listing.user_id,
    )
    if listing.legacy_report_id is not None:
        statement = statement.where(
            UserReportAssociation.legacy_report_id == listing.legacy_report_id
        )
    return list(
        session.exec(
            statement.order_by(
                col(UserReportAssociation.created_at),
                col(UserReportAssociation.id),
            )
            .offset(listing.offset)
            .limit(listing.limit + 1)
        ).all()
    )


def read_all_user_report_rows(
    session: Session, *, user_id: UUID
) -> list[UserReportAssociation]:
    """Return every association the user owns, in every country, in creation order."""
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
    """Return the user's saved policy with this id in this country, or None."""
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
    """Return whether the user has a saved policy with this id in this country."""
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
