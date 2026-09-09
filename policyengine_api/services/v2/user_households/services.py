"""Application services for native v2 user-household associations."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session

from policyengine_api.services.v2.user_households.database_connectors.creates import (
    create_user_household,
)
from policyengine_api.services.v2.user_households.database_connectors.deletes import (
    delete_user_household,
)
from policyengine_api.services.v2.user_households.database_connectors.reads import (
    read_household_for_association,
    read_user,
    read_user_household_row,
    read_user_household_rows,
)
from policyengine_api.services.v2.user_households.database_connectors.updates import (
    update_user_household,
)
from policyengine_api.services.v2.user_households.database_session import (
    UserHouseholdDatabaseSession,
)
from policyengine_api.services.v2.user_households.transformations import (
    user_household_page,
    user_household_read,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreationInput,
    UserHouseholdPage,
    UserHouseholdRead,
    UserHouseholdUpdateInput,
)
from policyengine_api.services.v2.user_households.validators import (
    require_user_household,
    validate_association_creation,
    validate_association_household,
)


def read_complete_user_household(
    session: Session,
    *,
    country_id: str,
    association_id: UUID,
) -> UserHouseholdRead:
    association = require_user_household(
        read_user_household_row(
            session,
            country_id=country_id,
            association_id=association_id,
        ),
        association_id=association_id,
    )
    return user_household_read(association)


def read_user_household_page(
    session: Session,
    *,
    country_id: str,
    user_id: UUID,
    household_id: UUID | None,
    offset: int,
    limit: int,
) -> UserHouseholdPage:
    rows = read_user_household_rows(
        session,
        country_id=country_id,
        user_id=user_id,
        household_id=household_id,
        offset=offset,
        limit=limit,
    )
    return user_household_page(rows, offset=offset, limit=limit)


class V2UserHouseholdService:
    """Sequence association operations through explicit database sessions."""

    def __init__(self, database_session: UserHouseholdDatabaseSession) -> None:
        self._database_session = database_session

    def create_user_household(
        self,
        association_input: UserHouseholdCreationInput,
    ) -> UserHouseholdRead:
        with self._database_session.transaction() as session:
            household = read_household_for_association(
                session,
                association_input.household_id,
            )
            validate_association_creation(
                association_input,
                user=read_user(session, association_input.user_id),
                household=household,
            )
            return user_household_read(
                create_user_household(session, association_input)
            )

    def get_user_household(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> UserHouseholdRead:
        with self._database_session.read() as session:
            return read_complete_user_household(
                session,
                country_id=country_id,
                association_id=association_id,
            )

    def list_user_households(
        self,
        *,
        country_id: str,
        user_id: UUID,
        household_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserHouseholdPage:
        with self._database_session.read() as session:
            return read_user_household_page(
                session,
                country_id=country_id,
                user_id=user_id,
                household_id=household_id,
                offset=offset,
                limit=limit,
            )

    def patch_user_household(
        self,
        *,
        country_id: str,
        association_id: UUID,
        association_input: UserHouseholdUpdateInput,
    ) -> UserHouseholdRead:
        with self._database_session.transaction() as session:
            association = require_user_household(
                read_user_household_row(
                    session,
                    country_id=country_id,
                    association_id=association_id,
                ),
                association_id=association_id,
            )
            if "household_id" in association_input.model_fields_set:
                assert association_input.household_id is not None
                replacement = read_household_for_association(
                    session,
                    association_input.household_id,
                )
                validate_association_household(
                    country_id=association.country_id,
                    household_id=association_input.household_id,
                    household=replacement,
                )
            return user_household_read(
                update_user_household(session, association, association_input)
            )

    def delete_user_household(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> None:
        with self._database_session.transaction() as session:
            association = require_user_household(
                read_user_household_row(
                    session,
                    country_id=country_id,
                    association_id=association_id,
                ),
                association_id=association_id,
            )
            delete_user_household(session, association)
