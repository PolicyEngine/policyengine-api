"""Strict HTTP request models for admins' user-type routes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class UserTypePatchRequest(BaseModel):
    """The signed-in type an admin gives a user."""

    model_config = ConfigDict(extra="forbid")

    user_type: Literal["standard", "author", "admin"]
