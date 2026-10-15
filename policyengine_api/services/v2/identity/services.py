"""Find, provision, and convert the v2 user a request acts as.

Every user-owned route resolves its principal once per request inside its own
v2 transaction. A provisioning strategy, selected from the principal's type,
decides how:

- ``StandardAccountProvisioning`` serves a verified sign-in identity. The
  first request for an unknown ``(issuer, subject)`` provisions a standard
  ``users`` row (with the request country as its primary country) and a
  ``user_identities`` row, on reads as well as writes. Concurrent first
  requests are reconciled by ``UNIQUE(issuer, subject)``: the loser rolls its
  savepoint back and re-reads the winner's identity, so exactly one user is
  created. There is no implicit adoption of legacy users and email is never
  used for linking.
- ``UnauthenticatedAccountProvisioning`` serves a signed-out browser whose
  credential is a UUID. Only writes provision its unauthenticated user, with
  the browser's UUID as ``users.id``; a read for an absent user finds nothing.
  A UUID that names a standard user is refused.

:func:`convert_unauthenticated_user_in_session` moves a browser's
unauthenticated user into a signed-in account at sign-in.

Only standard user UUIDs are logged. An unauthenticated user's UUID is its
credential, so its log records carry only the user type.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserType
from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.identity.database_connectors.creates import (
    create_provisioned_user,
    create_unauthenticated_user,
    create_user_identity,
)
from policyengine_api.services.v2.identity.database_connectors.deletes import (
    delete_unauthenticated_user,
)
from policyengine_api.services.v2.identity.database_connectors.reads import (
    read_unauthenticated_user_for_update,
    read_user,
    read_user_identity,
)
from policyengine_api.services.v2.identity.database_connectors.updates import (
    reassign_user_associations,
    update_user_identity_activity,
    update_user_to_standard,
)
from policyengine_api.services.v2.identity.database_session import (
    provisioning_savepoint,
)
from policyengine_api.services.v2.identity.transformations import (
    converted_primary_country,
    identity_refresh_required,
    refreshed_identity_email,
    standard_resolved_user,
    unauthenticated_resolved_user,
)
from policyengine_api.services.v2.identity.types import (
    AccountConversion,
    AccountConversionOutcome,
    AccountPrincipal,
    AccountProvisioningStrategy,
    ResolvedUser,
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from policyengine_api.services.v2.identity.validators import (
    require_concurrent_identity,
    require_provisioned_user,
    require_unauthenticated_user,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session

logger = logging.getLogger(__name__)

# A second attempt covers an unauthenticated user deleted (by its own account
# deletion, or by a merge at sign-in) between the insert and the re-read.
UNAUTHENTICATED_PROVISIONING_ATTEMPTS = 2


class StandardAccountProvisioning:
    """Provision the standard user of a verified sign-in identity on any request."""

    def __init__(self, principal: UserPrincipal) -> None:
        self._principal = principal

    def find_in_session(self, session: Session) -> ResolvedUser | None:
        identity = read_user_identity(
            session,
            issuer=self._principal.issuer,
            subject=self._principal.subject,
        )
        if identity is None:
            return None
        return standard_resolved_user(identity.user_id, email=identity.email)

    def resolve_in_session(
        self,
        session: Session,
        *,
        country_id: str,
        now: datetime | None = None,
    ) -> ResolvedUser:
        principal = self._principal
        seen_at = now or utc_now()
        identity = read_user_identity(
            session,
            issuer=principal.issuer,
            subject=principal.subject,
        )
        if identity is not None:
            if identity_refresh_required(identity, email=principal.email, now=seen_at):
                update_user_identity_activity(
                    session,
                    identity,
                    email=refreshed_identity_email(identity, principal.email),
                    seen_at=seen_at,
                )
            return standard_resolved_user(identity.user_id, email=identity.email)

        with provisioning_savepoint(session) as savepoint:
            user = create_provisioned_user(session, primary_country=country_id)
            created_user_id = create_user_identity(
                session,
                user_id=user.id,
                issuer=principal.issuer,
                subject=principal.subject,
                email=principal.email,
                seen_at=seen_at,
            )
            if created_user_id is None:
                savepoint.rollback()

        if created_user_id is not None:
            logger.info(
                "provisioned_v2_user",
                extra={
                    "policyengine_attributes": {
                        "v2_user_id": str(created_user_id),
                        "user_type": UserType.STANDARD.value,
                    }
                },
            )
            return standard_resolved_user(created_user_id, email=principal.email)

        concurrent = require_concurrent_identity(
            read_user_identity(
                session,
                issuer=principal.issuer,
                subject=principal.subject,
            )
        )
        return standard_resolved_user(concurrent.user_id, email=concurrent.email)

    def resolve_for_read_in_session(
        self,
        session: Session,
        *,
        country_id: str,
    ) -> ResolvedUser | None:
        # A signed-in account exists from its first request, read or write.
        return self.resolve_in_session(session, country_id=country_id)


class UnauthenticatedAccountProvisioning:
    """Provision a signed-out browser's unauthenticated user on its first write."""

    def __init__(self, principal: UnauthenticatedPrincipal) -> None:
        self._principal = principal

    def find_in_session(self, session: Session) -> ResolvedUser | None:
        user = require_unauthenticated_user(read_user(session, self._principal.user_id))
        return None if user is None else unauthenticated_resolved_user(user)

    def resolve_in_session(
        self,
        session: Session,
        *,
        country_id: str,
        now: datetime | None = None,
    ) -> ResolvedUser:
        # An unauthenticated user has no primary country or sign-in activity.
        del country_id, now
        user_id = self._principal.user_id
        created = False
        user = None
        for _attempt in range(UNAUTHENTICATED_PROVISIONING_ATTEMPTS):
            created = create_unauthenticated_user(session, user_id=user_id)
            # The share lock keeps a conversion or merge at sign-in from
            # changing this user until the write commits, and waits for one
            # already in progress.
            user = require_unauthenticated_user(
                read_user(session, user_id, for_share=True)
            )
            if user is not None:
                break
        provisioned = require_provisioned_user(user)
        if created:
            logger.info(
                "provisioned_v2_user",
                extra={
                    "policyengine_attributes": {
                        "user_type": UserType.UNAUTHENTICATED.value
                    }
                },
            )
        return unauthenticated_resolved_user(provisioned)

    def resolve_for_read_in_session(
        self,
        session: Session,
        *,
        country_id: str,
    ) -> ResolvedUser | None:
        # Reads never provision: an absent user simply owns no records.
        del country_id
        return self.find_in_session(session)


def account_provisioning_for(
    principal: AccountPrincipal,
) -> AccountProvisioningStrategy:
    """Select the provisioning strategy for a principal's type."""

    if isinstance(principal, UnauthenticatedPrincipal):
        return UnauthenticatedAccountProvisioning(principal)
    return StandardAccountProvisioning(principal)


def find_principal_user_in_session(
    session: Session,
    principal: AccountPrincipal,
) -> ResolvedUser | None:
    """Return the existing user for a principal without provisioning one."""

    return account_provisioning_for(principal).find_in_session(session)


def resolve_principal_user_in_session(
    session: Session,
    principal: AccountPrincipal,
    *,
    country_id: str,
    now: datetime | None = None,
) -> ResolvedUser:
    """Return the principal's v2 user, provisioning it on first use."""

    return account_provisioning_for(principal).resolve_in_session(
        session, country_id=country_id, now=now
    )


def resolve_principal_user_for_read_in_session(
    session: Session,
    principal: AccountPrincipal,
    *,
    country_id: str,
) -> ResolvedUser | None:
    """Return the user a read-only operation acts as.

    A standard principal is provisioned as on any request. An unauthenticated
    principal is not: ``None`` means it owns no records yet.
    """

    return account_provisioning_for(principal).resolve_for_read_in_session(
        session, country_id=country_id
    )


def convert_unauthenticated_user_in_session(
    session: Session,
    *,
    unauthenticated_user_id: UUID,
    principal: UserPrincipal,
    country_id: str,
    now: datetime | None = None,
) -> AccountConversion:
    """Move a browser's unauthenticated user into a signed-in account.

    The unauthenticated user's row is locked first (a standard user's row is
    never locked): concurrent conversions of one browser run one at a time,
    and each waits for that browser's writes in progress, which in turn wait
    for it.

    - No user with the identity yet: the unauthenticated user becomes it in
      place, keeping its ID and therefore every association it owns.
    - The identity already has a standard user: every association moves to
      that user unchanged, and the unauthenticated user is deleted.
    - No unauthenticated user, or the ID names a standard user (one already
      converted, or anyone else's): nothing is touched, and the identity's
      user is resolved as on any request.

    A concurrent first request for the same identity is reconciled by
    ``UNIQUE(issuer, subject)``: when it wins, this conversion merges into
    its user instead.
    """

    seen_at = now or utc_now()
    standard_provisioning = StandardAccountProvisioning(principal)
    unauthenticated_user = read_unauthenticated_user_for_update(
        session, unauthenticated_user_id
    )
    if unauthenticated_user is None:
        return AccountConversion(
            owner=standard_provisioning.resolve_in_session(
                session, country_id=country_id, now=seen_at
            ),
            outcome=AccountConversionOutcome.NONE,
        )

    converted = (
        standard_provisioning.find_in_session(session) is None
        and create_user_identity(
            session,
            user_id=unauthenticated_user.id,
            issuer=principal.issuer,
            subject=principal.subject,
            email=principal.email,
            seen_at=seen_at,
        )
        is not None
    )
    if converted:
        update_user_to_standard(
            session,
            unauthenticated_user,
            primary_country=converted_primary_country(
                unauthenticated_user, country_id=country_id
            ),
        )
        return AccountConversion(
            owner=standard_resolved_user(
                unauthenticated_user.id, email=principal.email
            ),
            outcome=AccountConversionOutcome.CONVERTED,
        )

    owner = standard_provisioning.resolve_in_session(
        session, country_id=country_id, now=seen_at
    )
    reassign_user_associations(
        session,
        from_user_id=unauthenticated_user.id,
        to_user_id=owner.user_id,
    )
    delete_unauthenticated_user(session, user_id=unauthenticated_user.id)
    return AccountConversion(owner=owner, outcome=AccountConversionOutcome.MERGED)
