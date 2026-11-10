"""Account services for ``/v2/me``, and admins' deletion of users' accounts.

Each ``/v2/me`` operation finds or provisions the caller's v2 user through the
principal's provisioning strategy. A signed-in principal's user is
provisioned, as a standard user, on first use; a signed-out browser's
unauthenticated user exists only after its first write, so reading,
exporting, or deleting an absent one finds nothing. Only signed-in principals
edit account details.

Upgrading moves a browser's unauthenticated user into the signed-in account
at sign-in. Deleting the last admin's account is refused. Deleting a
signed-in account, one's own or, for an admin, another user's by ID, removes
the user's legacy mappings, then the user (identities and associations
cascade), and finally the Auth0 users of its sign-in identities when the
Management API is configured; deleting an unauthenticated account removes
only its user and associations. Only signed-in user UUIDs are logged, and
each admin's deletion is recorded with the admin's and the user's.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserType
from policyengine_api.services.v2.identity.database_connectors.deletes import (
    delete_unauthenticated_user,
)
from policyengine_api.services.v2.identity.services import (
    convert_unauthenticated_user_in_session,
    find_principal_user_in_session,
    resolve_principal_user_for_read_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import (
    AccountPrincipal,
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from policyengine_api.services.v2.user_accounts.database_connectors.deletes import (
    delete_account_legacy_user_mappings,
    delete_account_user,
)
from policyengine_api.services.v2.user_accounts.database_connectors.reads import (
    read_account_user,
    read_identity_subjects,
)
from policyengine_api.services.v2.user_accounts.database_connectors.updates import (
    update_account_user,
)
from policyengine_api.services.v2.user_accounts.transformations import (
    account_read,
    account_update_values,
)
from policyengine_api.services.v2.user_accounts.types import (
    AccountDeletion,
    AccountExport,
    AccountRead,
    AccountUpdateInput,
    AccountUpgrade,
    Auth0UserDeleter,
)
from policyengine_api.services.v2.user_accounts.validators import (
    AccountDeletionUnavailableError,
    AccountIdentityDeletionError,
    require_account,
    require_editable_account,
    require_resolved_account,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.user_accounts.database_session import (
        AccountDatabaseSession,
    )

logger = logging.getLogger(__name__)

# The runtime event recording each admin's deletion of a user's account.
ADMIN_ACCOUNT_DELETION_EVENT = "admin_deleted_v2_user_account"
# The messages of AccountIdentityDeletionError, formatted with
# ``undeleted_count`` and ``subject_count``. DELETE /v2/me's names neither: a
# retry with the same token deletes that token's Auth0 user.
OWN_ACCOUNT_AUTH0_FAILURE_MESSAGE = (
    "Account data was deleted but the sign-in account could not be removed; "
    "retry the request"
)
# A retry finds no user (404), so the admin is told what remains to remove.
ADMIN_DELETION_AUTH0_FAILURE_MESSAGE = (
    "The account's data was deleted, but Auth0 users of its sign-in identities "
    "remain ({undeleted_count} of {subject_count}); find them in Auth0 by the "
    "person's email and delete them there"
)


class V2AccountService:
    """Sequence account operations through explicit sessions."""

    def __init__(
        self,
        database_session: AccountDatabaseSession,
        *,
        auth0_user_deleter_factory: Callable[[], Auth0UserDeleter | None] | None = None,
    ) -> None:
        """Open every session through ``database_session``.

        ``auth0_user_deleter_factory`` is called only when a signed-in account is
        deleted; without it, or when it returns None, the Auth0 user is kept.
        """
        self._database_session = database_session
        self._auth0_user_deleter_factory = auth0_user_deleter_factory

    def _prepared_auth0_user_deleter(self) -> Auth0UserDeleter | None:
        """Build and authenticate the Auth0 deleter before any data changes.

        Only account deletion needs the Management API, so its settings are
        read here rather than for every /v2/me request.
        """
        if self._auth0_user_deleter_factory is None:
            return None
        try:
            deleter = self._auth0_user_deleter_factory()
            if deleter is not None:
                deleter.prepare_deletion()
        except Exception as error:
            logger.warning(
                "auth0_user_deletion_unavailable",
                extra={"policyengine_attributes": {"error_type": type(error).__name__}},
            )
            msg = "Account deletion is temporarily unavailable; nothing was deleted"
            raise AccountDeletionUnavailableError(msg) from error
        return deleter

    def get_account(
        self, *, principal: AccountPrincipal, country_id: str
    ) -> AccountRead:
        """Return the caller's account, provisioning a signed-in caller's user.

        Raise AccountNotFoundError for a signed-out browser that has not saved
        anything yet.
        """
        with self._database_session.transaction() as session:
            owner = require_resolved_account(
                resolve_principal_user_for_read_in_session(
                    session, principal, country_id=country_id
                )
            )
            user = require_account(read_account_user(session, owner.user_id))
            return account_read(user, email=owner.email)

    def update_account(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        account_input: AccountUpdateInput,
    ) -> AccountRead:
        """Change only the supplied account fields and return the account.

        Raise AccountEditRequiresSignInError for a signed-out browser.
        """
        signed_in = require_editable_account(principal)
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, signed_in, country_id=country_id
            )
            user = require_account(read_account_user(session, owner.user_id))
            return account_read(
                update_account_user(
                    session, user, account_update_values(account_input)
                ),
                email=owner.email,
            )

    def export_account(
        self, *, principal: AccountPrincipal, country_id: str
    ) -> AccountExport:
        """Return the caller's account and every association it owns, in all countries.

        A signed-out browser with no saved work gets an empty export with no user.
        """
        from policyengine_api.services.v2.user_households.services import (
            read_all_user_households,
        )
        from policyengine_api.services.v2.user_policies.services import (
            read_all_user_policies,
        )
        from policyengine_api.services.v2.user_reports.services import (
            read_all_user_reports,
        )
        from policyengine_api.services.v2.user_simulations.services import (
            read_all_user_simulations,
        )

        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            if owner is None:
                return AccountExport(
                    user=None,
                    policies=(),
                    households=(),
                    simulations=(),
                    reports=(),
                )
            user = require_account(read_account_user(session, owner.user_id))
            return AccountExport(
                user=account_read(user, email=owner.email),
                policies=read_all_user_policies(session, user_id=owner.user_id),
                households=read_all_user_households(session, user_id=owner.user_id),
                simulations=read_all_user_simulations(session, user_id=owner.user_id),
                reports=read_all_user_reports(session, user_id=owner.user_id),
            )

    def upgrade_account(
        self,
        *,
        principal: UserPrincipal,
        unauthenticated_user_id: UUID,
        country_id: str,
    ) -> AccountUpgrade:
        """Move a browser's unauthenticated user into the signed-in account.

        The browser's user becomes the account, merges into an existing one, or
        is absent (outcome ``none``); see convert_unauthenticated_user_in_session.
        """
        with self._database_session.transaction() as session:
            conversion = convert_unauthenticated_user_in_session(
                session,
                unauthenticated_user_id=unauthenticated_user_id,
                principal=principal,
                country_id=country_id,
            )
            user = require_account(read_account_user(session, conversion.owner.user_id))
            upgrade = AccountUpgrade(
                account=account_read(user, email=conversion.owner.email),
                outcome=conversion.outcome,
            )
        # A converted user's ID was a browser credential, so no ID is logged.
        logger.info(
            "upgraded_v2_user",
            extra={"policyengine_attributes": {"outcome": upgrade.outcome.value}},
        )
        return upgrade

    def delete_account(self, *, principal: AccountPrincipal) -> AccountDeletion:
        """Delete the caller's user, its associations and, if configured, Auth0 users.

        Deleting an absent account succeeds with no user ID. Raise
        AccountDeletionUnavailableError, before anything is deleted, when the
        Auth0 deleter cannot authenticate, and AccountIdentityDeletionError when
        the data was deleted but an Auth0 user was not.
        """
        if isinstance(principal, UnauthenticatedPrincipal):
            return self._delete_unauthenticated_account(principal)
        return self._delete_standard_account(principal)

    def _delete_unauthenticated_account(
        self, principal: UnauthenticatedPrincipal
    ) -> AccountDeletion:
        """Delete a browser's unauthenticated user; there is no Auth0 user."""
        with self._database_session.transaction() as session:
            owner = find_principal_user_in_session(session, principal)
            if owner is not None:
                delete_unauthenticated_user(session, user_id=owner.user_id)
        if owner is None:
            return AccountDeletion(user_id=None, auth0_subjects=())
        logger.info(
            "deleted_v2_user_account",
            extra={
                "policyengine_attributes": {"user_type": UserType.UNAUTHENTICATED.value}
            },
        )
        return AccountDeletion(user_id=owner.user_id, auth0_subjects=())

    def _delete_standard_account(self, principal: UserPrincipal) -> AccountDeletion:
        auth0_user_deleter = self._prepared_auth0_user_deleter()
        with self._database_session.transaction() as session:
            owner = find_principal_user_in_session(session, principal)
            if owner is None:
                subjects: tuple[str, ...] = (principal.subject,)
            else:
                # Imported here: the user-type service is loaded only when
                # used, like this one.
                from policyengine_api.services.v2.user_types.services import (
                    require_admin_remains_after_deletion_in_session,
                )

                require_admin_remains_after_deletion_in_session(
                    session, user_id=owner.user_id
                )
                subjects = _delete_signed_in_user_in_session(
                    session, user_id=owner.user_id, issuer=principal.issuer
                ) or (principal.subject,)
        deleted_user_id = owner.user_id if owner is not None else None
        if deleted_user_id is not None:
            logger.info(
                "deleted_v2_user_account",
                extra={"policyengine_attributes": {"v2_user_id": str(deleted_user_id)}},
            )
        return _delete_auth0_users(
            auth0_user_deleter,
            subjects,
            deleted_user_id=deleted_user_id,
            failure_message_template=OWN_ACCOUNT_AUTH0_FAILURE_MESSAGE,
        )

    def delete_user_account_as_admin(
        self, *, principal: UserPrincipal, user_id: UUID
    ) -> AccountDeletion:
        """Delete a signed-in user's account for an admin, as for one's own.

        The Auth0 deleter is prepared, the account deleted and its sign-in
        identities' Auth0 users removed exactly as ``delete_account`` does for
        the caller's own account; an admin may delete their own account this
        way too. Raise UserTypeBelowMinimumError unless the caller is an admin,
        SignedInUserNotFoundError when no signed-in user has ``user_id``, and
        LastAdminDeletionError when that user is the only admin, each with
        nothing deleted. Raise AccountDeletionUnavailableError and
        AccountIdentityDeletionError as ``delete_account`` does; since a retry
        finds no user, the latter's message says how many Auth0 users remain
        and to find them in Auth0 by the person's email.
        """
        auth0_user_deleter = self._prepared_auth0_user_deleter()
        with self._database_session.transaction() as session:
            # Imported here: the user-type service is loaded only when used,
            # like this one.
            from policyengine_api.services.v2.user_types.services import (
                require_admin_may_delete_user_in_session,
            )

            admin_user_id = require_admin_may_delete_user_in_session(
                session, principal=principal, user_id=user_id
            )
            subjects = _delete_signed_in_user_in_session(
                session, user_id=user_id, issuer=principal.issuer
            )
        _record_admin_account_deletion(
            admin_user_id=admin_user_id, deleted_user_id=user_id
        )
        return _delete_auth0_users(
            auth0_user_deleter,
            subjects,
            deleted_user_id=user_id,
            failure_message_template=ADMIN_DELETION_AUTH0_FAILURE_MESSAGE,
        )


def _delete_signed_in_user_in_session(
    session: Session, *, user_id: UUID, issuer: str
) -> tuple[str, ...]:
    """Delete a signed-in user's legacy mappings and the user; return Auth0 subjects.

    The subjects are those of the user's identities from ``issuer``, the
    tenant whose tokens the Public API accepts, oldest first. They are read
    before the identities cascade away with the user.
    """
    subjects = tuple(read_identity_subjects(session, user_id=user_id, issuer=issuer))
    delete_account_legacy_user_mappings(session, user_id=user_id)
    delete_account_user(session, user_id=user_id)
    return subjects


def _delete_auth0_users(
    auth0_user_deleter: Auth0UserDeleter | None,
    subjects: tuple[str, ...],
    *,
    deleted_user_id: UUID | None,
    failure_message_template: str,
) -> AccountDeletion:
    """Delete a deleted account's Auth0 users, after its data is gone.

    Without a deleter, or without a subject to delete, the Auth0 users are
    kept and the skip is logged. Every subject is tried, since the identities
    that named them are already gone; then, if any deletion failed, raise
    AccountIdentityDeletionError with ``failure_message_template`` formatted
    with the counts. No subject, email or token is logged.
    """
    logged_user_id = str(deleted_user_id) if deleted_user_id is not None else None
    if auth0_user_deleter is None:
        logger.warning(
            "auth0_user_deletion_skipped_not_configured",
            extra={"policyengine_attributes": {"v2_user_id": logged_user_id}},
        )
        return AccountDeletion(user_id=deleted_user_id, auth0_subjects=())
    if not subjects:
        # Only an admin's deletion can find none: the user's identities were
        # all from another issuer, whose Auth0 users this tenant can't delete.
        logger.warning(
            "auth0_user_deletion_skipped_no_identity_under_issuer",
            extra={"policyengine_attributes": {"v2_user_id": logged_user_id}},
        )
        return AccountDeletion(user_id=deleted_user_id, auth0_subjects=())
    failures: list[Exception] = []
    for subject in subjects:
        try:
            auth0_user_deleter.delete_user(subject)
        except Exception as error:  # noqa: BLE001  # the remaining subjects are still tried; the failures are raised below
            failures.append(error)
    if not failures:
        return AccountDeletion(user_id=deleted_user_id, auth0_subjects=subjects)
    logger.warning(
        "auth0_user_deletion_failed",
        extra={
            "policyengine_attributes": {
                "v2_user_id": logged_user_id,
                "error_type": type(failures[0]).__name__,
                "auth0_user_count": len(subjects),
                "undeleted_auth0_user_count": len(failures),
            }
        },
    )
    message = failure_message_template.format(
        undeleted_count=len(failures), subject_count=len(subjects)
    )
    raise AccountIdentityDeletionError(
        message, undeleted_auth0_user_count=len(failures)
    ) from failures[0]


def _record_admin_account_deletion(
    *, admin_user_id: UUID, deleted_user_id: UUID
) -> None:
    """Record which admin deleted which user's account, by v2 user IDs only.

    It is a runtime event at INFO, not a standard-library log record, because
    the deployed process keeps the root logger at WARNING, which drops INFO
    records. It is recorded once the data is deleted, before the Auth0 users
    are removed. Recording never changes the response.
    """
    # Telemetry must never fail a deletion that has already happened.
    with contextlib.suppress(Exception):
        from policyengine_api import (  # noqa: PLC0415  # importing it builds the process-wide runtime, which commands that load the account service must not
            observability,
        )

        observability.get_runtime().event(
            ADMIN_ACCOUNT_DELETION_EVENT,
            severity="INFO",
            attributes={
                "admin_v2_user_id": str(admin_user_id),
                "v2_user_id": str(deleted_user_id),
            },
        )
