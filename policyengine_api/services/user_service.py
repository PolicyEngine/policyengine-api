"""v1 user profiles, keyed by internal user ID and by Auth0 ID."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import UserProfile

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class UserService:
    """User-profile operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        """Use this session factory, or the application's v1 one if omitted."""
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
        """Create a profile for this Auth0 ID, or return the one that already exists.

        Return ``(created, profile)``.
        """
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
        """Return the profile with this user ID, or else this Auth0 ID, or None.

        ``user_id`` wins when both are given. Raise ValueError if neither is given.
        """
        if auth0_id is None and user_id is None:
            msg = "you must specify either auth0_id or user_id"
            raise ValueError(msg)
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
        """Set the given non-None fields on a profile; return None if it does not exist.

        Raise ValueError if ``user_id`` is None.
        """
        if user_id is None:
            msg = "you must specify either auth0_id or user_id"
            raise ValueError(msg)
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
