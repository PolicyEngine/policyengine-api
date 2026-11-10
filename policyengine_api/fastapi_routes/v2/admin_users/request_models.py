"""Strict HTTP request models for admins' user-type routes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class UserTypePatchRequest(BaseModel):
    """The signed-in type an admin gives a user, and the type the admin last read.

    ``expected_user_type`` is the user's type as the admin last read it. When
    the user's stored type differs, someone changed it since, and the change
    is refused (409) so it can't silently overwrite theirs.
    """

    model_config = ConfigDict(extra="forbid")

    user_type: Literal["standard", "author", "admin"]
    expected_user_type: Literal["standard", "author", "admin"]
