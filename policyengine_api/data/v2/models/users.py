"""Canonical SQLModel tables for v2 users and their sign-in identities.

A user is either ``standard`` (backed by one or more verified sign-in
identities, as every Stage 10 legacy-mapping user is) or ``unauthenticated``.
An unauthenticated user's ``id`` is the random UUID a signed-out browser
generates and sends as its credential; every other user column stays NULL.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import IdentifiedModel, utc_now

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import (
        UserHouseholdAssociation,
        UserPolicy,
        UserReportAssociation,
        UserSimulationAssociation,
    )
    from policyengine_api.data.v2.models.reports import Report


class UserType(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    STANDARD = "standard"


class User(IdentifiedModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "primary_country IN ('us', 'uk')",
            name="ck_users_primary_country",
        ),
        sa.CheckConstraint(
            "user_type IN ('unauthenticated', 'standard')",
            name="ck_users_user_type",
        ),
        sa.CheckConstraint(
            "user_type = 'unauthenticated' OR primary_country IS NOT NULL",
            name="ck_users_standard_primary_country",
        ),
    )

    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320, index=True)
    primary_country: str | None = Field(default=None, max_length=2)
    # The server default keeps inserts by earlier Public API revisions, which
    # do not map this column, creating standard users.
    user_type: str = Field(
        default=UserType.STANDARD.value,
        max_length=16,
        sa_column_kwargs={"server_default": UserType.STANDARD.value},
    )

    reports: list["Report"] = Relationship(back_populates="user")
    identities: list["UserIdentity"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    household_associations: list["UserHouseholdAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    policy_associations: list["UserPolicy"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    simulation_associations: list["UserSimulationAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    report_associations: list["UserReportAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )


class UserIdentity(IdentifiedModel, table=True):
    """Map one verified external sign-in subject to one v2 user.

    The issuer is stored in its normalized trailing-slash form. The email is
    informational only: it is never unique and never used to link accounts.
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        sa.UniqueConstraint(
            "issuer",
            "subject",
            name="uq_user_identities_issuer_subject",
        ),
        sa.Index("ix_user_identities_user_id", "user_id"),
    )

    user_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE")
    issuer: str = Field(sa_type=sa.Text)
    subject: str = Field(sa_type=sa.Text)
    email: str | None = Field(default=None, max_length=320)
    last_seen_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        sa_column_kwargs={"server_default": sa.func.now()},
    )

    user: User = Relationship(back_populates="identities")
