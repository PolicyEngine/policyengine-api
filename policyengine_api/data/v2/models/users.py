"""Canonical SQLModel tables for v2 users, their sign-in identities and types.

A user is ``unauthenticated``, or a signed-in user of type ``standard``,
``author`` or ``admin``, backed by one or more verified sign-in identities
(every Stage 10 legacy-mapping user is standard). An unauthenticated user's
``id`` is the random UUID a signed-out browser generates and sends as its
credential; every other user column stays NULL. Each change of a signed-in
user's type is recorded, and admins invite email addresses to become authors
or admins.
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
    """A user's type, listed from the fewest permissions to the most.

    An ``unauthenticated`` user belongs to a signed-out browser. Every
    signed-in user is ``standard``, ``author`` or ``admin``, and each type has
    every permission of the types listed before it, so the order of the
    members is the order a minimum type is checked against.
    """

    UNAUTHENTICATED = "unauthenticated"
    STANDARD = "standard"
    AUTHOR = "author"
    ADMIN = "admin"


_ALLOWED_USER_TYPES_SQL = ", ".join(f"'{user_type.value}'" for user_type in UserType)
# The types a signed-in user can have, which admins and the type script set.
SIGNED_IN_USER_TYPES = (UserType.STANDARD, UserType.AUTHOR, UserType.ADMIN)
_SIGNED_IN_USER_TYPES_SQL = ", ".join(
    f"'{user_type.value}'" for user_type in SIGNED_IN_USER_TYPES
)


class UserTypeChangeSource(StrEnum):
    """What changed a signed-in user's type."""

    # An admin, through the Public API's admin routes.
    ADMIN_ROUTE = "admin_route"
    # An operator, through scripts/set_v2_user_type.py.
    SCRIPT = "script"
    # The user, by accepting an admin's email invitation.
    INVITATION = "invitation"


# The types an admin's email invitation can grant.
INVITATION_USER_TYPES = (UserType.AUTHOR, UserType.ADMIN)
_INVITATION_USER_TYPES_SQL = ", ".join(
    f"'{user_type.value}'" for user_type in INVITATION_USER_TYPES
)
_USER_TYPE_CHANGE_SOURCES_SQL = ", ".join(
    f"'{source.value}'" for source in UserTypeChangeSource
)


class User(IdentifiedModel, table=True):
    """A v2 user account, unique by email when one is given.

    A signed-in user, of any type but ``unauthenticated``, always has a
    primary country. Deleting a user deletes their sign-in identities and
    saved associations; reports they own are kept without an owner.
    """

    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            f"user_type IN ({_ALLOWED_USER_TYPES_SQL})",
            name="ck_users_user_type_allowed",
        ),
        # Named for the standard type alone, but required of every signed-in type.
        sa.CheckConstraint(
            "user_type = 'unauthenticated' OR primary_country IS NOT NULL",
            name="ck_users_standard_primary_country",
        ),
    )

    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320, index=True)
    primary_country: str | None = Field(
        default=None,
        max_length=2,
        foreign_key="countries.id",
        ondelete="RESTRICT",
    )
    # The server default keeps inserts by earlier Public API revisions, which
    # do not map this column, creating standard users. Signing in never
    # changes a stored type.
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


class UserTypeChange(IdentifiedModel, table=True):
    """One change of a signed-in user's type; together, the user's type history.

    ``created_at`` is when the type changed. ``changed_by_user_id`` names the
    admin who changed it through the admin routes, or who sent the invitation
    the user accepted. It is empty for a change the type script made, and
    becomes empty if that admin's account is deleted. ``dismissed_at`` is when
    the user dismissed the app's notice of the change. Deleting the user
    deletes its history.
    """

    __tablename__ = "user_type_changes"
    __table_args__ = (
        sa.CheckConstraint(
            f"previous_user_type IN ({_SIGNED_IN_USER_TYPES_SQL})",
            name="ck_user_type_changes_previous_user_type",
        ),
        sa.CheckConstraint(
            f"new_user_type IN ({_SIGNED_IN_USER_TYPES_SQL})",
            name="ck_user_type_changes_new_user_type",
        ),
        sa.CheckConstraint(
            "previous_user_type <> new_user_type",
            name="ck_user_type_changes_changed_type",
        ),
        # Alembic compares checks by name only, so this one was renamed from
        # ck_user_type_changes_source when invitation was allowed.
        sa.CheckConstraint(
            f"source IN ({_USER_TYPE_CHANGE_SOURCES_SQL})",
            name="ck_user_type_changes_source_allowed",
        ),
        sa.Index("ix_user_type_changes_user_id_created_at", "user_id", "created_at"),
        # Deleting any user sets its changes' admin to NULL, which searches here.
        sa.Index("ix_user_type_changes_changed_by_user_id", "changed_by_user_id"),
    )

    user_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE")
    changed_by_user_id: UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    previous_user_type: str = Field(max_length=16)
    new_user_type: str = Field(max_length=16)
    source: str = Field(max_length=16)
    dismissed_at: datetime | None = Field(
        default=None, sa_type=sa.DateTime(timezone=True)
    )


class UserInvitation(IdentifiedModel, table=True):
    """An admin's invitation for an email address to become an author or admin.

    The invitation's token is sent only in its email; only the token's SHA-256
    digest, in hexadecimal, is stored. An invitation is open until it is
    accepted or revoked, and can be accepted only before ``expires_at``.
    Resending gives it a new token and expiry. ``last_sent_at`` is when the
    email with the current token was sent, and ``last_send_error`` names why
    the last send failed. ``invited_by_user_id`` is the admin who created or
    last resent it, and becomes empty if that admin's account is deleted.
    ``accepted_by_user_id`` is the user who accepted it: deleting that user's
    account deletes the invitation, whose address was the user's own.
    """

    __tablename__ = "user_invitations"
    __table_args__ = (
        sa.CheckConstraint(
            f"user_type IN ({_INVITATION_USER_TYPES_SQL})",
            name="ck_user_invitations_user_type",
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name="ck_user_invitations_accepted_or_revoked",
        ),
        sa.UniqueConstraint("token_hash", name="uq_user_invitations_token_hash"),
        # Deleting any user sets the invitations it sent to NULL and deletes
        # those it accepted, which searches here.
        sa.Index("ix_user_invitations_invited_by_user_id", "invited_by_user_id"),
        sa.Index("ix_user_invitations_accepted_by_user_id", "accepted_by_user_id"),
    )

    email: str = Field(max_length=320)
    user_type: str = Field(max_length=16)
    token_hash: str = Field(max_length=64)
    invited_by_user_id: UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    expires_at: datetime = Field(sa_type=sa.DateTime(timezone=True))
    last_sent_at: datetime | None = Field(
        default=None, sa_type=sa.DateTime(timezone=True)
    )
    last_send_error: str | None = Field(default=None, max_length=64)
    accepted_at: datetime | None = Field(
        default=None, sa_type=sa.DateTime(timezone=True)
    )
    accepted_by_user_id: UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="CASCADE"
    )
    revoked_at: datetime | None = Field(
        default=None, sa_type=sa.DateTime(timezone=True)
    )
