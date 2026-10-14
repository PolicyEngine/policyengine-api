"""Account services for ``/v2/me``.

Each operation finds or provisions the caller's v2 user through the
principal's provisioning strategy. A signed-in principal's standard user is
provisioned on first use; a signed-out browser's unauthenticated user exists
only after its first write, so reading, exporting, or deleting an absent one
finds nothing. Only signed-in principals edit account details.

Upgrading moves a browser's unauthenticated user into the signed-in account
at sign-in. Deleting a standard account removes the user's legacy mappings,
then the user (identities and associations cascade), and finally the Auth0
user when the Management API is configured; deleting an unauthenticated
account removes only its user and associations. Only standard user UUIDs are
logged.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from uuid import UUID

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
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
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


logger = logging.getLogger(__name__)


class V2AccountService:
    """Sequence account operations through explicit sessions."""

    def __init__(
        self,
        database_session: AccountDatabaseSession,
        *,
        auth0_user_deleter_factory: Callable[[], Auth0UserDeleter | None] | None = None,
    ) -> None:
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
            raise AccountDeletionUnavailableError(
                "Account deletion is temporarily unavailable; nothing was deleted"
            ) from error
        return deleter

    def get_account(
        self, *, principal: AccountPrincipal, country_id: str
    ) -> AccountRead:
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
                subjects = tuple(
                    read_identity_subjects(
                        session, user_id=owner.user_id, issuer=principal.issuer
                    )
                ) or (principal.subject,)
                delete_account_legacy_user_mappings(session, user_id=owner.user_id)
                delete_account_user(session, user_id=owner.user_id)
        deleted_user_id = owner.user_id if owner is not None else None
        if deleted_user_id is not None:
            logger.info(
                "deleted_v2_user_account",
                extra={"policyengine_attributes": {"v2_user_id": str(deleted_user_id)}},
            )

        if auth0_user_deleter is None:
            logger.warning(
                "auth0_user_deletion_skipped_not_configured",
                extra={
                    "policyengine_attributes": {
                        "v2_user_id": (
                            str(deleted_user_id)
                            if deleted_user_id is not None
                            else None
                        )
                    }
                },
            )
            return AccountDeletion(user_id=deleted_user_id, auth0_subjects=())
        try:
            for subject in subjects:
                auth0_user_deleter.delete_user(subject)
        except Exception as error:
            logger.warning(
                "auth0_user_deletion_failed",
                extra={
                    "policyengine_attributes": {
                        "v2_user_id": (
                            str(deleted_user_id)
                            if deleted_user_id is not None
                            else None
                        ),
                        "error_type": type(error).__name__,
                    }
                },
            )
            raise AccountIdentityDeletionError(
                "Account data was deleted but the sign-in account could not be "
                "removed; retry the request"
            ) from error
        return AccountDeletion(user_id=deleted_user_id, auth0_subjects=subjects)
