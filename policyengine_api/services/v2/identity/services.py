"""Resolve and provision the v2 user for a verified sign-in identity.

Every user-owned route runs :func:`resolve_principal_user_in_session` once per
request inside its own v2 transaction. The first request for an unknown
``(issuer, subject)`` provisions a ``users`` row (with the request country as
its primary country) and a ``user_identities`` row. Concurrent first requests
are reconciled by ``UNIQUE(issuer, subject)``: the loser rolls its savepoint
back and re-reads the winner's identity, so exactly one user is created.
There is no implicit adoption of legacy users and email is never used for
linking. Only the v2 user UUID is logged.
"""

from __future__ import annotations

from datetime import datetime
import logging

from sqlmodel import Session

from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.identity.database_connectors.creates import (
    create_provisioned_user,
    create_user_identity,
)
from policyengine_api.services.v2.identity.database_connectors.reads import (
    read_user_identity,
)
from policyengine_api.services.v2.identity.database_connectors.updates import (
    update_user_identity_activity,
)
from policyengine_api.services.v2.identity.database_session import (
    provisioning_savepoint,
)
from policyengine_api.services.v2.identity.transformations import (
    identity_refresh_required,
    refreshed_identity_email,
)
from policyengine_api.services.v2.identity.types import ResolvedUser, UserPrincipal
from policyengine_api.services.v2.identity.validators import (
    require_concurrent_identity,
)


logger = logging.getLogger(__name__)


def find_principal_user_in_session(
    session: Session,
    principal: UserPrincipal,
) -> ResolvedUser | None:
    """Return the existing user for a principal without provisioning one."""

    identity = read_user_identity(
        session,
        issuer=principal.issuer,
        subject=principal.subject,
    )
    if identity is None:
        return None
    return ResolvedUser(
        user_id=identity.user_id,
        email=identity.email,
        provisioned=False,
    )


def resolve_principal_user_in_session(
    session: Session,
    principal: UserPrincipal,
    *,
    country_id: str,
    now: datetime | None = None,
) -> ResolvedUser:
    """Return the principal's v2 user, provisioning it on first use."""

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
        return ResolvedUser(
            user_id=identity.user_id,
            email=identity.email,
            provisioned=False,
        )

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
            extra={"policyengine_attributes": {"v2_user_id": str(created_user_id)}},
        )
        return ResolvedUser(
            user_id=created_user_id,
            email=principal.email,
            provisioned=True,
        )

    concurrent = require_concurrent_identity(
        read_user_identity(
            session,
            issuer=principal.issuer,
            subject=principal.subject,
        )
    )
    return ResolvedUser(
        user_id=concurrent.user_id,
        email=concurrent.email,
        provisioned=False,
    )
