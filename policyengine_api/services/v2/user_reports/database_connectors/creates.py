"""Database inserts for v2 user-report associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from policyengine_api.data.v2.models import UserReportAssociation
from policyengine_api.services.v2.associations.validators import violates_foreign_key
from policyengine_api.services.v2.user_reports.validators import (
    SAVED_REPORT_FOREIGN_KEY,
    report_not_found,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.services.v2.user_reports.types import UserReportCreationInput


def create_user_report(
    session: Session,
    association_input: UserReportCreationInput,
) -> UserReportAssociation:
    """Insert an association and return it with its database-generated fields loaded.

    Raise AssociationReportNotFoundError when the report's foreign key refuses
    the insert: the service checked the report in this transaction, so it was
    deleted after that check.
    """
    association = UserReportAssociation(**association_input.model_dump())
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
