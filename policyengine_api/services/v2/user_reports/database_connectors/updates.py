"""Database updates for mutable v2 user-report association fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError

from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.associations.validators import violates_foreign_key
from policyengine_api.services.v2.user_reports.validators import (
    SAVED_REPORT_FOREIGN_KEY,
    report_not_found,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserReportAssociation


def update_user_report(
    session: Session,
    association: UserReportAssociation,
    values: Mapping[str, Any],
) -> UserReportAssociation:
    """Set the given column values, bump ``updated_at`` and return the row.

    Raise AssociationReportNotFoundError when the report's foreign key refuses
    a new ``report_id``: the service checked the report in this transaction,
    so it was deleted after that check.
    """
    for field_name, value in values.items():
        setattr(association, field_name, value)
    association.updated_at = utc_now()
    session.add(association)
    try:
        session.flush()
    except IntegrityError as error:
        if association.report_id is not None and violates_foreign_key(
            error, SAVED_REPORT_FOREIGN_KEY
        ):
            raise report_not_found(
                report_id=association.report_id, country_id=association.country_id
            ) from error
        raise
    session.refresh(association)
    return association
