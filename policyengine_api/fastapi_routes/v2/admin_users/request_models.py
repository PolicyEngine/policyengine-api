"""Strict HTTP request models for admins' user-type routes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class UserTypePatchRequest(BaseModel):
    """The signed-in type an admin gives a user, and the type the admin last read.

    expected_user_type is the user's type as the admin last read it. When the
    request would change the type and the stored type differs from
    expected_user_type, the change is refused (409) and nothing is written.
    When the user already has user_type, nothing changes (200), whatever
    expected_user_type is. Only the type is compared: a type changed and
    changed back since the read is not detected.
    """

    model_config = ConfigDict(extra="forbid")

    user_type: Literal["standard", "author", "admin"]
    expected_user_type: Literal["standard", "author", "admin"]
