"""Strict HTTP response models for admins' user routes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.me.response_models import MeExportResult

if TYPE_CHECKING:
    from policyengine_api.services.v2.user_types.types import (
        AdminUserPage,
        AdminUserRead,
        UserTypeChangeRead,
    )


class StrictAdminUserAPIModel(BaseModel):
    """Base for admin user responses; rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class AdminUserItem(StrictAdminUserAPIModel):
    """A signed-in user as admins see it.

    With Auth0 user profile settings, ``email``, ``first_name`` and
    ``last_name`` are read from Auth0 for each request and never stored: the
    user's sign-in identities from the users' Auth0 tenant are looked up, the
    most recently seen first, and a verified email comes before an unverified
    one. Where Auth0 has no value, or can't answer, the stored value is
    returned: the email of the most recently seen of the user's identities
    that has one, else the user's own, and the user's stored names. When
    neither has a first or last name, Auth0's full name, if it isn't an
    email address, is the first name. ``last_seen_at`` is when the user's
    most recently seen identity was last seen.
    """

    id: UUID
    user_type: Literal["standard", "author", "admin"]
    email: str | None
    first_name: str | None
    last_name: str | None
    primary_country: str | None
    created_at: datetime
    last_seen_at: datetime | None

    @classmethod
    def from_read(cls, user: AdminUserRead) -> AdminUserItem:
        """Convert the service's read model; the type is validated as a literal."""
        return cls.model_validate(
            {
                "id": user.id,
                "user_type": user.user_type.value,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "primary_country": user.primary_country,
                "created_at": user.created_at,
                "last_seen_at": user.last_seen_at,
            }
        )


class AdminUserPageResult(StrictAdminUserAPIModel):
    """One page of signed-in users, newest first."""

    items: list[AdminUserItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: AdminUserPage) -> AdminUserPageResult:
        """Convert the service's page."""
        return cls(
            items=[AdminUserItem.from_read(user) for user in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


class AdminUserPageResponse(StrictAdminUserAPIModel):
    """The response for a page of signed-in users."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: AdminUserPageResult


class AdminUserResult(StrictAdminUserAPIModel):
    """One signed-in user."""

    item: AdminUserItem


class AdminUserResponse(StrictAdminUserAPIModel):
    """The response for one signed-in user."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: AdminUserResult


class UserTypeChangeItem(StrictAdminUserAPIModel):
    """One recorded change of a signed-in user's type.

    ``source`` is ``admin_route`` for a change an admin made through these
    routes, named by ``changed_by_user_id`` and ``changed_by_email``,
    ``invitation`` for one the user made by accepting an admin's email
    invitation, which names that admin, and ``script`` for one the type
    script made, which names no admin. ``changed_by_user_id`` is also null
    once that admin's account is deleted.
    ``changed_by_email`` is read from Auth0 like an admin user item's email,
    else stored.
    """

    id: UUID
    user_id: UUID
    previous_user_type: Literal["standard", "author", "admin"]
    new_user_type: Literal["standard", "author", "admin"]
    changed_by_user_id: UUID | None
    changed_by_email: str | None
    source: Literal["admin_route", "invitation", "script"]
    created_at: datetime

    @classmethod
    def from_read(cls, change: UserTypeChangeRead) -> UserTypeChangeItem:
        """Convert the service's read model; the types are validated as literals."""
        return cls.model_validate(
            {
                "id": change.id,
                "user_id": change.user_id,
                "previous_user_type": change.previous_user_type.value,
                "new_user_type": change.new_user_type.value,
                "changed_by_user_id": change.changed_by_user_id,
                "changed_by_email": change.changed_by_email,
                "source": change.source.value,
                "created_at": change.created_at,
            }
        )


class UserTypeChangeListResult(StrictAdminUserAPIModel):
    """A signed-in user's recorded type changes, newest first."""

    items: list[UserTypeChangeItem]


class UserTypeChangeListResponse(StrictAdminUserAPIModel):
    """The response for a signed-in user's recorded type changes."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: UserTypeChangeListResult


class AdminUserSavedItemsResponse(StrictAdminUserAPIModel):
    """The response for a signed-in user's saved items, in every country.

    ``result`` is what the user's own ``GET /v2/me/export`` returns: the user,
    with the email admins see for it, and every policy, household, simulation
    and report it saved.
    """

    status: Literal["ok"] = "ok"
    message: None = None
    result: MeExportResult
