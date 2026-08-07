from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import UserProfile


class UserService:
    """User-profile operations performed through a caller-owned ORM Session."""

    def create_profile(
        self,
        session: Session,
        primary_country: str,
        auth0_id: str,
        username: str | None,
        user_since: int,
    ) -> tuple[bool, UserProfile]:
        existing = self.get_profile(session, auth0_id=auth0_id)
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
        session: Session,
        auth0_id: str | None = None,
        user_id: int | str | None = None,
    ) -> UserProfile | None:
        if auth0_id is None and user_id is None:
            raise ValueError("you must specify either auth0_id or user_id")
        condition = (
            UserProfile.user_id == user_id
            if user_id is not None
            else UserProfile.auth0_id == auth0_id
        )
        return session.scalar(select(UserProfile).where(condition))

    def update_profile(
        self,
        session: Session,
        user_id: int,
        primary_country: str | None,
        username: str | None,
        user_since: int | None,
    ) -> UserProfile | None:
        if user_id is None:
            raise ValueError("you must specify either auth0_id or user_id")
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
