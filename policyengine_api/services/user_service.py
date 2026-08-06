from __future__ import annotations

from typing import Any

from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import UserDAO


class UserService:
    def __init__(self, users: UserDAO | None = None):
        self._users = users

    @property
    def users(self) -> UserDAO:
        if self._users is None:
            self._users = UserDAO(build_v1_session_manager())
        return self._users

    def create_profile(
        self,
        primary_country: str,
        auth0_id: str,
        username: str | None,
        user_since: int,
    ) -> tuple[bool, Any]:
        row = self.get_profile(auth0_id=auth0_id)
        if row is not None:
            return False, row
        self.users.create_profile(auth0_id, username, primary_country, user_since)
        return True, self.get_profile(auth0_id=auth0_id)

    def get_profile(
        self, auth0_id: str | None = None, user_id: int | None = None
    ) -> Any | None:
        if auth0_id is None and user_id is None:
            raise ValueError("you must specify either auth0_id or user_id")
        return self.users.get_profile(user_id=user_id, auth0_id=auth0_id)

    def update_profile(
        self,
        user_id: int,
        primary_country: str | None,
        username: str | None,
        user_since: int,
    ) -> bool:
        if user_id is None:
            raise ValueError("you must specify either auth0_id or user_id")
        return self.users.update_profile(
            user_id,
            primary_country=primary_country,
            username=username,
            user_since=user_since,
        )
