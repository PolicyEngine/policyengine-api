"""Signed-in account services for ``/v2/me``.

Reads, updates, exports, and imports resolve (and on first use provision) the
caller's v2 user from the verified session principal. Imports are idempotent
on ``(user_id, client_ref)``: unknown v1 references, invalid items, and
client_refs the user already holds in another country are skipped and reported
rather than failing the request. Deletion removes the
user's legacy mappings, then the user (identities and associations cascade),
and finally the Auth0 user when the Management API is configured. Only v2 user
UUIDs are logged.
"""

from __future__ import annotations

from collections.abc import Callable
import logging

from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
from policyengine_api.services.v2.associations.validators import (
    require_legacy_reference_checker,
)
from policyengine_api.services.v2.identity.services import (
    find_principal_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind
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
    AccountImportInput,
    AccountImportResult,
    AccountRead,
    AccountUpdateInput,
)
from policyengine_api.services.v2.user_accounts.validators import (
    AccountIdentityDeletionError,
    client_ref_conflict_skips,
    partition_import_items,
    partition_known_legacy_items,
    require_account,
)
from policyengine_api.services.v2.user_households.services import (
    import_user_households_in_session,
    read_all_user_households,
)
from policyengine_api.services.v2.user_households.types import UserHouseholdImportItem
from policyengine_api.services.v2.user_policies.services import (
    import_user_policies_in_session,
    read_all_user_policies,
)
from policyengine_api.services.v2.user_policies.types import UserPolicyImportItem
from policyengine_api.services.v2.user_reports.services import (
    import_user_reports_in_session,
    read_all_user_reports,
)
from policyengine_api.services.v2.user_reports.types import UserReportImportItem
from policyengine_api.services.v2.user_simulations.services import (
    import_user_simulations_in_session,
    read_all_user_simulations,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationImportItem,
)


logger = logging.getLogger(__name__)


class V2AccountService:
    """Sequence signed-in account operations through explicit sessions."""

    def __init__(
        self,
        database_session: AccountDatabaseSession,
        *,
        legacy_references: LegacyReferenceChecker | None = None,
        auth0_user_deleter: Callable[[str], None] | None = None,
    ) -> None:
        self._database_session = database_session
        self._legacy_references = legacy_references
        self._auth0_user_deleter = auth0_user_deleter

    def get_account(self, *, principal: UserPrincipal, country_id: str) -> AccountRead:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            user = require_account(
                read_account_user(session, owner.user_id), user_id=owner.user_id
            )
            return account_read(user, email=owner.email)

    def update_account(
        self,
        *,
        principal: UserPrincipal,
        country_id: str,
        account_input: AccountUpdateInput,
    ) -> AccountRead:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            user = require_account(
                read_account_user(session, owner.user_id), user_id=owner.user_id
            )
            return account_read(
                update_account_user(
                    session, user, account_update_values(account_input)
                ),
                email=owner.email,
            )

    def export_account(
        self, *, principal: UserPrincipal, country_id: str
    ) -> AccountExport:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            user = require_account(
                read_account_user(session, owner.user_id), user_id=owner.user_id
            )
            return AccountExport(
                user=account_read(user, email=owner.email),
                policies=read_all_user_policies(session, user_id=owner.user_id),
                households=read_all_user_households(session, user_id=owner.user_id),
                simulations=read_all_user_simulations(session, user_id=owner.user_id),
                reports=read_all_user_reports(session, user_id=owner.user_id),
            )

    def import_records(
        self,
        *,
        principal: UserPrincipal,
        country_id: str,
        import_input: AccountImportInput,
    ) -> AccountImportResult:
        policies, policy_skips = partition_import_items(
            import_input.policies, UserPolicyImportItem
        )
        households, household_skips = partition_import_items(
            import_input.households, UserHouseholdImportItem
        )
        simulations, simulation_skips = partition_import_items(
            import_input.simulations, UserSimulationImportItem
        )
        reports, report_skips = partition_import_items(
            import_input.reports, UserReportImportItem
        )

        existing = require_legacy_reference_checker(
            self._legacy_references
        ).existing_ids(
            country_id=country_id,
            requested={
                LegacyRecordKind.POLICY: [item.legacy_policy_id for item in policies],
                LegacyRecordKind.HOUSEHOLD: [
                    item.legacy_household_id for item in households
                ],
                LegacyRecordKind.SIMULATION: [
                    item.legacy_simulation_id for item in simulations
                ],
                LegacyRecordKind.REPORT: [item.legacy_report_id for item in reports],
            },
        )
        known_policies, unknown_policies = partition_known_legacy_items(
            policies,
            legacy_ids=[item.legacy_policy_id for item in policies],
            client_refs=[item.client_ref for item in policies],
            existing=existing[LegacyRecordKind.POLICY],
        )
        known_households, unknown_households = partition_known_legacy_items(
            households,
            legacy_ids=[item.legacy_household_id for item in households],
            client_refs=[item.client_ref for item in households],
            existing=existing[LegacyRecordKind.HOUSEHOLD],
        )
        known_simulations, unknown_simulations = partition_known_legacy_items(
            simulations,
            legacy_ids=[item.legacy_simulation_id for item in simulations],
            client_refs=[item.client_ref for item in simulations],
            existing=existing[LegacyRecordKind.SIMULATION],
        )
        known_reports, unknown_reports = partition_known_legacy_items(
            reports,
            legacy_ids=[item.legacy_report_id for item in reports],
            client_refs=[item.client_ref for item in reports],
            existing=existing[LegacyRecordKind.REPORT],
        )

        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            # Policies go first so reports can link to policies imported by the
            # same request.
            policy_import = import_user_policies_in_session(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                items=known_policies,
            )
            household_import = import_user_households_in_session(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                items=known_households,
            )
            simulation_import = import_user_simulations_in_session(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                items=known_simulations,
            )
            report_import = import_user_reports_in_session(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                items=known_reports,
            )

        return AccountImportResult(
            id_map={
                **policy_import.ids,
                **household_import.ids,
                **simulation_import.ids,
                **report_import.ids,
            },
            skipped=(
                *policy_skips,
                *unknown_policies,
                *client_ref_conflict_skips(policy_import.conflicting_client_refs),
                *household_skips,
                *unknown_households,
                *client_ref_conflict_skips(household_import.conflicting_client_refs),
                *simulation_skips,
                *unknown_simulations,
                *client_ref_conflict_skips(simulation_import.conflicting_client_refs),
                *report_skips,
                *unknown_reports,
                *client_ref_conflict_skips(report_import.conflicting_client_refs),
            ),
        )

    def delete_account(self, *, principal: UserPrincipal) -> AccountDeletion:
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
                extra={"v2_user_id": str(deleted_user_id)},
            )

        if self._auth0_user_deleter is None:
            logger.warning(
                "auth0_user_deletion_skipped_not_configured",
                extra={
                    "v2_user_id": (
                        str(deleted_user_id) if deleted_user_id is not None else None
                    )
                },
            )
            return AccountDeletion(user_id=deleted_user_id, auth0_subjects=())
        try:
            for subject in subjects:
                self._auth0_user_deleter(subject)
        except Exception as error:
            logger.warning(
                "auth0_user_deletion_failed",
                extra={
                    "v2_user_id": (
                        str(deleted_user_id) if deleted_user_id is not None else None
                    ),
                    "error_type": type(error).__name__,
                },
            )
            raise AccountIdentityDeletionError(
                "Account data was deleted but the sign-in account could not be "
                "removed; retry the request"
            ) from error
        return AccountDeletion(user_id=deleted_user_id, auth0_subjects=subjects)
