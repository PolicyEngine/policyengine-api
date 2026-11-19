"""Router-facing and migration-facing services for users' saved dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_for_read_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.user_dynamics.database_connectors.creates import (
    create_user_dynamic,
)
from policyengine_api.services.v2.user_dynamics.database_connectors.deletes import (
    delete_user_dynamic,
)
from policyengine_api.services.v2.user_dynamics.database_connectors.reads import (
    read_all_user_dynamic_rows,
    read_dynamic_for_association,
    read_owned_user_dynamic_row,
    read_user_dynamic_rows,
)
from policyengine_api.services.v2.user_dynamics.database_connectors.updates import (
    update_user_dynamic,
)
from policyengine_api.services.v2.user_dynamics.transformations import (
    owned_user_dynamic_input,
    user_dynamic_page,
    user_dynamic_read,
)
from policyengine_api.services.v2.user_dynamics.types import (
    UserDynamicFilter,
    UserDynamicListing,
)
from policyengine_api.services.v2.user_dynamics.validators import (
    require_user_dynamic,
    validate_association_dynamic,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserDynamic
    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.user_dynamics.database_session import (
        UserDynamicDatabaseSession,
    )
    from policyengine_api.services.v2.user_dynamics.types import (
        UserDynamicCreateFields,
        UserDynamicCreationInput,
        UserDynamicPage,
        UserDynamicRead,
        UserDynamicUpdateInput,
    )


def require_dynamic_in_country(
    session: Session, *, country_id: str, dynamic_id: UUID
) -> None:
    """Check that the dynamic exists and is stored in ``country_id``.

    Raise AssociationDynamicNotFoundError or AssociationDynamicCountryConflictError.
    """
    validate_association_dynamic(
        country_id=country_id,
        dynamic_id=dynamic_id,
        dynamic=read_dynamic_for_association(session, dynamic_id),
    )


def create_user_dynamic_in_session(
    session: Session, creation_input: UserDynamicCreationInput
) -> UserDynamicRead:
    """Save a dynamic for the user that ``creation_input`` names, in ``session``.

    This is what D4 · 1's migration calls to give a v1 saved policy a saved
    dynamic; the routes call it once they have resolved the owner. The user
    must exist, and the dynamic must be stored in the saved dynamic's country
    (AssociationDynamicNotFoundError or AssociationDynamicCountryConflictError).
    The caller's transaction commits it.
    """
    require_dynamic_in_country(
        session,
        country_id=creation_input.country_id,
        dynamic_id=creation_input.dynamic_id,
    )
    return user_dynamic_read(create_user_dynamic(session, creation_input))


def read_owned_user_dynamic(
    session: Session,
    *,
    user_id: UUID | None,
    country_id: str,
    association_id: UUID,
) -> UserDynamic:
    """``user_id`` is None for an unauthenticated user that owns nothing yet."""
    return require_user_dynamic(
        None
        if user_id is None
        else read_owned_user_dynamic_row(
            session,
            user_id=user_id,
            country_id=country_id,
            association_id=association_id,
        ),
        association_id=association_id,
    )


def read_all_user_dynamics(
    session: Session, *, user_id: UUID
) -> tuple[UserDynamicRead, ...]:
    """Return every saved dynamic owned by a user, across countries."""
    return tuple(
        user_dynamic_read(row)
        for row in read_all_user_dynamic_rows(session, user_id=user_id)
    )


class V2UserDynamicService:
    """Sequence owner-scoped saved-dynamic operations through explicit sessions.

    The owner always comes from the verified session principal: a signed-in
    user or a signed-out browser. Reads never provision a browser's
    unauthenticated user; one that does not exist yet owns no records.
    """

    def __init__(self, database_session: UserDynamicDatabaseSession) -> None:
        """Open sessions through ``database_session``."""
        self._database_session = database_session

    def create_user_dynamic(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserDynamicCreateFields,
    ) -> UserDynamicRead:
        """Save a dynamic for the principal, provisioning their v2 user if needed.

        The dynamic must be stored in this country
        (AssociationDynamicNotFoundError or AssociationDynamicCountryConflictError).
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session,
                principal,
                country_id=association_input.country_id,
            )
            return create_user_dynamic_in_session(
                session,
                owned_user_dynamic_input(association_input, user_id=owner.user_id),
            )

    def get_user_dynamic(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserDynamicRead:
        """Return the principal's saved dynamic in this country.

        Raise UserDynamicNotFoundError when it is absent or another user's. A
        signed-out browser that has not saved anything yet owns nothing.
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            return user_dynamic_read(
                read_owned_user_dynamic(
                    session,
                    user_id=None if owner is None else owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def list_user_dynamics(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        dynamic_filter: UserDynamicFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserDynamicPage:
        """Return a page of the principal's saved dynamics in this country.

        ``dynamic_filter`` narrows it to one dynamic. A signed-out browser that
        has not saved anything yet gets an empty page.
        """
        selected = dynamic_filter if dynamic_filter is not None else UserDynamicFilter()
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            if owner is None:
                return user_dynamic_page([], offset=offset, limit=limit)
            rows = read_user_dynamic_rows(
                session,
                UserDynamicListing(
                    country_id=country_id,
                    user_id=owner.user_id,
                    dynamic_id=selected.dynamic_id,
                    offset=offset,
                    limit=limit,
                ),
            )
            return user_dynamic_page(rows, offset=offset, limit=limit)

    def patch_user_dynamic(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserDynamicUpdateInput,
    ) -> UserDynamicRead:
        """Update the supplied fields of the principal's saved dynamic in this country.

        It keeps its id, owner, country and creation time. A new ``dynamic_id``
        must be stored in this country (AssociationDynamicNotFoundError or
        AssociationDynamicCountryConflictError). Raise UserDynamicNotFoundError
        when the saved dynamic is not the principal's.
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            saved_dynamic = read_owned_user_dynamic(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                association_id=association_id,
            )
            if association_input.dynamic_id is not None:
                require_dynamic_in_country(
                    session,
                    country_id=country_id,
                    dynamic_id=association_input.dynamic_id,
                )
            return user_dynamic_read(
                update_user_dynamic(session, saved_dynamic, association_input)
            )

    def delete_user_dynamic(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete the principal's saved dynamic in this country.

        Raise UserDynamicNotFoundError when it is not the principal's.
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            delete_user_dynamic(
                session,
                read_owned_user_dynamic(
                    session,
                    user_id=owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                ),
            )
