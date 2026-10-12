"""Database updates for mutable v2 user-report association fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlmodel import Session

from policyengine_api.data.v2.models import UserReportAssociation
from policyengine_api.data.v2.models.base import utc_now


def update_user_report(
    session: Session,
    association: UserReportAssociation,
    values: Mapping[str, Any],
) -> UserReportAssociation:
    for field_name, value in values.items():
        setattr(association, field_name, value)
    association.updated_at = utc_now()
    session.add(association)
    session.flush()
    session.refresh(association)
    return association
