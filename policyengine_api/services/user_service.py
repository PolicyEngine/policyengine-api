from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import UserDAO, V1UnitOfWork


class UserService:
    def __init__(
        self,
        users: UserDAO | None = None,
        *,
        unit_of_work: V1UnitOfWork | None = None,
    ):
        self._users = users
        self._unit_of_work = unit_of_work

    @property
    def unit_of_work(self) -> V1UnitOfWork:
        if self._unit_of_work is None:
            self._unit_of_work = V1UnitOfWork(build_v1_session_manager())
        return self._unit_of_work

    @contextmanager
    def _repository(self, *, write: bool = False):
        if self._users is not None:
            yield self._users
            return
        boundary = self.unit_of_work.transaction if write else self.unit_of_work.read
        with boundary() as daos:
            yield daos.users

    def create_profile(
        self,
        primary_country: str,
        auth0_id: str,
        username: str | None,
        user_since: int,
    ) -> tuple[bool, Any]:
        with self._repository(write=True) as users:
            row = users.get_profile(auth0_id=auth0_id)
            if row is not None:
                return False, row
            users.create_profile(auth0_id, username, primary_country, user_since)
            return True, users.get_profile(auth0_id=auth0_id)

    def get_profile(
        self, auth0_id: str | None = None, user_id: int | None = None
    ) -> Any | None:
        if auth0_id is None and user_id is None:
            raise ValueError("you must specify either auth0_id or user_id")
        with self._repository() as users:
            return users.get_profile(user_id=user_id, auth0_id=auth0_id)

    def update_profile(
        self,
        user_id: int,
        primary_country: str | None,
        username: str | None,
        user_since: int,
    ) -> bool:
        if user_id is None:
            raise ValueError("you must specify either auth0_id or user_id")
        with self._repository(write=True) as users:
            return users.update_profile(
                user_id,
                primary_country=primary_country,
                username=username,
                user_since=user_since,
            )
