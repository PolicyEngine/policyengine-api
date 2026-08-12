from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import UserProfile


class UserService:
    """User-profile operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    def create_profile(
        self,
        primary_country: str,
        auth0_id: str,
        username: str | None,
        user_since: int,
    ) -> tuple[bool, UserProfile]:
        with self._sessions.begin() as session:
            return self._create_profile(
                session,
                primary_country,
                auth0_id,
                username,
                user_since,
            )

    @classmethod
    def _create_profile(
        cls,
        session: Session,
        primary_country: str,
        auth0_id: str,
        username: str | None,
        user_since: int,
    ) -> tuple[bool, UserProfile]:
        existing = cls._get_profile(session, auth0_id=auth0_id)
        if existing is not None:
            return False, existing
        profile = UserProfile(
            auth0_id=auth0_id,
            username=username,
            primary_country=primary_country,
            user_since=user_since,
        )
        session.add(profile)
        session.flush()
        return True, profile

    def get_profile(
        self,
        auth0_id: str | None = None,
        user_id: int | str | None = None,
    ) -> UserProfile | None:
        if auth0_id is None and user_id is None:
            raise ValueError("you must specify either auth0_id or user_id")
        with self._sessions() as session:
            return self._get_profile(session, auth0_id, user_id)

    @staticmethod
    def _get_profile(
        session: Session,
        auth0_id: str | None = None,
        user_id: int | str | None = None,
    ) -> UserProfile | None:
        condition = (
            UserProfile.user_id == user_id
            if user_id is not None
            else UserProfile.auth0_id == auth0_id
        )
        return session.scalar(select(UserProfile).where(condition))

    def update_profile(
        self,
        user_id: int,
        primary_country: str | None,
        username: str | None,
        user_since: int | None,
    ) -> UserProfile | None:
        if user_id is None:
            raise ValueError("you must specify either auth0_id or user_id")
        with self._sessions.begin() as session:
            return self._update_profile(
                session,
                user_id,
                primary_country,
                username,
                user_since,
            )

    @staticmethod
    def _update_profile(
        session: Session,
        user_id: int,
        primary_country: str | None,
        username: str | None,
        user_since: int | None,
    ) -> UserProfile | None:
        profile = session.get(UserProfile, user_id)
        if profile is None:
            return None
        if primary_country is not None:
            profile.primary_country = primary_country
        if username is not None:
            profile.username = username
        if user_since is not None:
            profile.user_since = user_since
        return profile
