"""Database inserts used by the operations on users' saved dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserDynamic

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.services.v2.user_dynamics.types import (
        UserDynamicCreationInput,
    )


def create_user_dynamic(
    session: Session, creation_input: UserDynamicCreationInput
) -> UserDynamic:
    """Insert a saved dynamic and return it with its generated fields loaded."""
    saved_dynamic = UserDynamic(**creation_input.model_dump())
    session.add(saved_dynamic)
    session.flush()
    session.refresh(saved_dynamic)
    return saved_dynamic
