"""Interfaces of the v2 resource services that native FastAPI routes depend on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from policyengine_api.fastapi_routes.saved_item_service_protocols import (
    V2UserDynamicResourceService,
    V2UserHouseholdResourceService,
    V2UserPolicyResourceService,
    V2UserReportResourceService,
    V2UserSimulationResourceService,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import UserType
    from policyengine_api.services.v2.countries.types import CountryRead
    from policyengine_api.services.v2.dynamics.types import (
        CheckedDynamicRead,
        NativeDynamicCreation,
        NativeDynamicCreationInput,
    )
    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationInput,
        HouseholdCalculationRead,
        HouseholdCalculationSubmitted,
    )
    from policyengine_api.services.v2.households.types import (
        HouseholdPage,
        HouseholdRead,
        NativeHouseholdCreation,
        NativeHouseholdCreationInput,
    )
    from policyengine_api.services.v2.identity.types import (
        AccountPrincipal,
        UserPrincipal,
    )
    from policyengine_api.services.v2.policies.types import (
        CheckedPolicyPage,
        CheckedPolicyRead,
        NativePolicyCreation,
        NativePolicyCreationInput,
    )
    from policyengine_api.services.v2.published_reports.types import (
        PublicationCreateInput,
        PublicationRead,
        PublicationUpdateInput,
        PublicationVersionInput,
        PublishedReportRead,
    )
    from policyengine_api.services.v2.simulation_service.types import (
        EconomySimulationCreationInput,
        ReportCreationInput,
    )
    from policyengine_api.services.v2.stored_reports.types import (
        StoredReportRead,
        StoredReportRunsRead,
        StoredReportSummaryRead,
    )
    from policyengine_api.services.v2.stored_simulations.types import SimulationRead
    from policyengine_api.services.v2.user_accounts.types import (
        AccountDeletion,
        AccountExport,
        AccountRead,
        AccountUpdateInput,
        AccountUpgrade,
    )
    from policyengine_api.services.v2.user_invitations.types import (
        AdminInvitationPage,
        AdminInvitationRead,
        AdminInvitationSearch,
        InvitationAcceptance,
    )
    from policyengine_api.services.v2.user_types.types import (
        AdminUserPage,
        AdminUserRead,
        AdminUserSearch,
        UserTypeChangeRead,
    )


__all__ = [
    "V2AccountResourceService",
    "V2CountryResourceService",
    "V2DynamicResourceService",
    "V2HouseholdCalculationResourceService",
    "V2HouseholdResourceService",
    "V2PolicyResourceService",
    "V2StoredReportResourceService",
    "V2StoredSimulationResourceService",
    "V2UserDynamicResourceService",
    "V2UserHouseholdResourceService",
    "V2UserInvitationResourceService",
    "V2UserPolicyResourceService",
    "V2UserReportResourceService",
    "V2UserSimulationResourceService",
    "V2UserTypeResourceService",
]


class V2CountryResourceService(Protocol):
    """Route-independent countries list read for one request."""

    def list_countries(self) -> list[CountryRead]:
        """Return every served country and its capability, ordered by ID."""
        ...


class V2PolicyResourceService(Protocol):
    """Route-independent native policy operations for one request."""

    def create_policy(
        self,
        command: NativePolicyCreationInput,
    ) -> NativePolicyCreation:
        """Store the policy, or return the identical one already stored.

        Policies are immutable and deduplicated by canonical content hash;
        ``created`` says whether this call inserted the policy.
        """
        ...

    def get_policy(self, *, country_id: str, policy_id: UUID) -> CheckedPolicyRead:
        """Return one policy of the country with its parameter values.

        Raise ``PolicyNotFoundError`` when no such policy exists in that country.
        """
        ...

    def list_policies(
        self,
        *,
        country_id: str,
        tax_benefit_model_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> CheckedPolicyPage:
        """Return a page of the country's policies, optionally for one model."""
        ...


class V2DynamicResourceService(Protocol):
    """Route-independent native dynamic operations, stored as policies are."""

    def create_dynamic(
        self, dynamic_input: NativeDynamicCreationInput
    ) -> NativeDynamicCreation:
        """Store the dynamic, or return the identical one; ``created`` says which."""
        ...

    def get_dynamic(self, *, country_id: str, dynamic_id: UUID) -> CheckedDynamicRead:
        """Return the country's dynamic, or raise ``DynamicNotFoundError``."""
        ...


class V2HouseholdResourceService(Protocol):
    """Route-independent native household operations for one request."""

    def create_household(
        self,
        household_input: NativeHouseholdCreationInput,
    ) -> NativeHouseholdCreation:
        """Store the household, or return the identical one already stored.

        Households are immutable and deduplicated by canonical content hash;
        ``created`` says whether this call inserted the household.
        """
        ...

    def get_household(
        self,
        *,
        country_id: str,
        household_id: UUID,
    ) -> HouseholdRead:
        """Return one household of the country.

        Raise ``HouseholdNotFoundError`` when no such household exists there.
        """
        ...

    def list_households(
        self,
        *,
        country_id: str,
        default_year: int | None,
        offset: int,
        limit: int,
    ) -> HouseholdPage:
        """Return a page of the country's households, optionally of one default year."""
        ...


class V2HouseholdCalculationResourceService(Protocol):
    """Route-independent household calculation operations for one request."""

    def submit_calculation(
        self, calculation: HouseholdCalculationInput
    ) -> HouseholdCalculationSubmitted:
        """Send a stored household's calculation to the simulation service.

        Raise ``HouseholdCalculationCountryError`` for a country without
        household calculations, ``HouseholdNotFoundError``,
        ``PolicyNotFoundError`` or ``DynamicNotFoundError`` for a record not
        stored in that country, ``HouseholdCalculationYearError`` for a
        household without a default year, ``PolicyParametersMissingError``
        (``DynamicParametersMissingError`` for a dynamic) for one setting
        parameters the running catalog version lacks, and the simulation
        service errors when it refuses the calculation.
        """
        ...

    def get_calculation(self, calculation_id: UUID) -> HouseholdCalculationRead:
        """Return the calculation household_jobs records.

        Raise ``HouseholdCalculationNotFoundError`` when there is no such job.
        """
        ...


class V2StoredReportResourceService(Protocol):
    """Route-independent report operations for one request."""

    def get_report(
        self,
        *,
        country_id: str,
        report_id: UUID,
        run_id: UUID | None = None,
        requester: AccountPrincipal | None = None,
    ) -> StoredReportRead:
        """Return the country's report, a run and that run's result, as a user sees it.

        The run is ``run_id``; without it, the requester's newest recorded
        run, else the report's newest succeeded unforced run, else its newest
        unforced run. The label and description are the requester's saved
        report's. The report is an economy report, a household report or a
        budget window. Raise ``StoredReportNotFoundError`` when the country
        has no such report, ``ReportRunNotFoundError`` when it has no run
        ``run_id``, ``StandardUserRequiresSignInError`` for an
        unauthenticated credential naming a signed-in user, and
        ``EconomyResultUnreadableError``, ``HouseholdResultUnreadableError`` or
        ``BudgetWindowResultUnreadableError`` when a succeeded run's result
        cannot be read.
        """
        ...

    def list_reports(
        self,
        *,
        country_id: str,
        report_ids: Sequence[UUID],
        requester: AccountPrincipal | None = None,
    ) -> tuple[StoredReportSummaryRead, ...]:
        """Return the country's reports of every kind among those named, in order.

        Each is read as ``get_report`` reads it without a run, as the
        requester sees it.
        """
        ...

    def search_reports(
        self,
        *,
        country_id: str,
        dataset_independent_key: str,
        requester: AccountPrincipal | None = None,
    ) -> tuple[StoredReportSummaryRead, ...]:
        """Return the country's reports with the dataset-independent key, newest first.

        At most ``MAXIMUM_LISTED_REPORTS``, the ones created last, each read
        as ``list_reports`` reads it.
        """
        ...

    def create_report(
        self,
        report_input: ReportCreationInput,
        *,
        requester: AccountPrincipal | None = None,
    ) -> StoredReportRead:
        """Create the report through the simulation service; return it as stored.

        It is answered with the run the simulation service named, created or
        joined. With a ``requester``, the request is recorded for its user
        once the simulation service has answered. Raise
        ``StandardUserRequiresSignInError`` for an unauthenticated credential
        that names a signed-in user, before anything is asked;
        ``EconomyCalculationsUnsupportedError`` for an economy report in a
        country without economy reports,
        ``HouseholdCalculationCountryError`` for a household report in a
        country without household calculations, ``HouseholdNotFoundError``
        for a household the country does not store,
        ``HouseholdCalculationYearError`` for one with no default year,
        ``PolicyNotFoundError`` or ``DynamicNotFoundError`` for a policy or
        dynamic the country does not store, ``PolicyParametersMissingError``
        (``DynamicParametersMissingError`` for a dynamic) for one setting
        parameters the running catalog lacks, ``SubmissionStorageError`` when the
        database or its catalog cannot be read for those checks, the
        simulation service's errors, ``ReportRunNotRecordedError`` when the
        request could not be recorded, and ``CreatedReportUnreadableError``
        when the report it created cannot be read back.
        """
        ...

    def rerun_report(
        self,
        *,
        country_id: str,
        report_id: UUID,
        force: bool,
        include_cliffs: bool = False,
        requester: AccountPrincipal | None = None,
    ) -> StoredReportRead:
        """Run the country's report again; return it with the run the request ended on.

        That is the run the simulation service named, created or joined.
        With ``include_cliffs``, it also starts the cliff calculations an
        economy report run's simulation runs lack; ``CliffsNotAvailableError``
        is raised, before anything is asked, for any other kind.
        With a ``requester``, the request is recorded for its user once the
        simulation service has answered, and
        ``StandardUserRequiresSignInError`` is raised, before anything is
        asked, for an unauthenticated credential that names a signed-in user.
        Raise ``StoredReportNotFoundError`` when the country has no such
        report; the errors of the country check a new report of its kind makes
        (economy calculations, or household calculations for a household
        report) and of the policy checks of its simulations, as
        ``create_report`` raises them (a household report's household is not
        checked again); the simulation service's errors, among them
        ``SimulationServiceConflictError`` when it will not run the report
        again now, ``ReportRunNotRecordedError`` when the request could not be
        recorded, and ``RerunReportUnreadableError`` when the report cannot
        be read back once its run was started, or when a budget window's
        answer names no window run (its ``run_id`` is then None, and nothing
        is recorded).
        """
        ...

    def list_report_runs(
        self, *, country_id: str, report_id: UUID
    ) -> StoredReportRunsRead:
        """Return the runs of the country's report, newest first.

        An economy or household report's are its report runs; a budget
        window's are its budget-window runs, each with its years. Raise
        ``StoredReportNotFoundError`` when the country has no such report.
        """
        ...


class V2PublishedReportResourceService(Protocol):
    """Route-independent publishing of saved reports, and their public read."""

    def publish_report(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        user_report_id: UUID,
        publication_input: PublicationCreateInput,
    ) -> PublicationRead:
        """Publish the principal's saved report, showing the run the input names."""
        ...

    def get_publication(
        self, *, principal: AccountPrincipal, country_id: str, user_report_id: UUID
    ) -> PublicationRead:
        """Return the principal's published report with every version."""
        ...

    def update_publication(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        user_report_id: UUID,
        publication_input: PublicationUpdateInput,
    ) -> PublicationRead:
        """Set the fields the edit sends on the principal's published report."""
        ...

    def add_publication_version(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        user_report_id: UUID,
        version_input: PublicationVersionInput,
    ) -> PublicationRead:
        """Move the principal's published report to another run, as a version."""
        ...

    def withdraw_publication(
        self, *, principal: AccountPrincipal, country_id: str, user_report_id: UUID
    ) -> None:
        """Delete the principal's published report with its versions."""
        ...

    def get_published_report(
        self, *, country_id: str, user_report_id: UUID, version_id: UUID | None
    ) -> PublishedReportRead:
        """Return a published report as anyone reads it, with no credential."""
        ...


class V2StoredSimulationResourceService(Protocol):
    """Route-independent simulation operations for one request."""

    def get_simulation(self, *, country_id: str, simulation_id: UUID) -> SimulationRead:
        """Return the country's simulation and its newest run.

        Raise ``StoredSimulationNotFoundError`` when there is none.
        """
        ...

    def create_simulation(
        self, simulation_input: EconomySimulationCreationInput
    ) -> SimulationRead:
        """Create the simulation through the simulation service; return it as stored.

        Raise the checks' and the simulation service's errors as
        ``V2StoredReportResourceService.create_report`` does, for the
        simulation's policy and dynamic, and ``CreatedSimulationUnreadableError`` when
        the simulation it created cannot be read back.
        """
        ...


class V2AccountResourceService(Protocol):
    """Route-independent account operations for one request."""

    def get_account(
        self, *, principal: AccountPrincipal, country_id: str
    ) -> AccountRead:
        """Return the caller's account, provisioning a signed-in user on first use.

        Raise ``AccountNotFoundError`` for an unauthenticated user that has not
        saved anything yet.
        """
        ...

    def update_account(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        account_input: AccountUpdateInput,
    ) -> AccountRead:
        """Change the supplied fields of a signed-in user's account and return it.

        Raise ``AccountEditRequiresSignInError`` for an unauthenticated user.
        """
        ...

    def export_account(
        self, *, principal: AccountPrincipal, country_id: str
    ) -> AccountExport:
        """Return the caller's account and all its associations, in every country."""
        ...

    def upgrade_account(
        self,
        *,
        principal: UserPrincipal,
        unauthenticated_user_id: UUID,
        country_id: str,
    ) -> AccountUpgrade:
        """Move a browser's unauthenticated user into the signed-in account.

        The outcome says whether it was converted in place, merged into an
        existing account, or absent.
        """
        ...

    def delete_account(self, *, principal: AccountPrincipal) -> AccountDeletion:
        """Delete the caller's user and associations; an absent user succeeds.

        A signed-in user's Auth0 user is deleted too when Auth0 Management is
        configured.
        """
        ...

    def delete_user_account_as_admin(
        self, *, principal: UserPrincipal, user_id: UUID
    ) -> AccountDeletion:
        """Delete a signed-in user's account for an admin, as for one's own.

        Raise ``UserTypeBelowMinimumError`` unless the caller is an admin,
        ``SignedInUserNotFoundError`` when no signed-in user has the ID, and
        ``LastAdminDeletionError`` when that user is the only admin, each with
        nothing deleted. Raise ``AccountDeletionUnavailableError`` before
        anything is deleted when the Auth0 deleter can't be prepared, and
        ``AccountIdentityDeletionError`` when the data was deleted but some of
        the user's Auth0 users were not.
        """
        ...

    def dismiss_type_change(
        self, *, principal: UserPrincipal, type_change_id: UUID
    ) -> None:
        """Record that the signed-in user dismissed the notice of a type change.

        Raise ``TypeChangeNotFoundError`` unless the user has this change.
        """
        ...


class V2UserTypeResourceService(Protocol):
    """Route-independent minimum user types and admins' changes to users' types."""

    def require_minimum_user_type(
        self, *, principal: AccountPrincipal, minimum: UserType
    ) -> UserType:
        """Return the caller's type; raise ``UserTypeBelowMinimumError`` below it."""
        ...

    def list_users(
        self, *, principal: AccountPrincipal, search: AdminUserSearch
    ) -> AdminUserPage:
        """Return one page of signed-in users, newest first, to an admin."""
        ...

    def get_user(self, *, principal: AccountPrincipal, user_id: UUID) -> AdminUserRead:
        """Return one signed-in user to an admin.

        Raise ``SignedInUserNotFoundError`` when no signed-in user has the ID.
        """
        ...

    def change_user_type(
        self,
        *,
        principal: AccountPrincipal,
        user_id: UUID,
        user_type: UserType,
        expected_user_type: UserType,
    ) -> AdminUserRead:
        """Change a signed-in user's type for an admin, recording the change.

        The type the user already has changes nothing, whatever
        ``expected_user_type`` is. Otherwise raise ``UserTypeChangedError`` when
        the stored type is no longer ``expected_user_type``, and
        ``LastAdminDemotionError`` when the change would leave no admin.
        """
        ...

    def list_user_type_changes(
        self, *, principal: AccountPrincipal, user_id: UUID
    ) -> tuple[UserTypeChangeRead, ...]:
        """Return a signed-in user's recorded type changes, newest first."""
        ...

    def get_user_saved_items(
        self, *, principal: AccountPrincipal, user_id: UUID
    ) -> AccountExport:
        """Return a signed-in user's account and saved items, in every country.

        The result is what the user's own export returns. Raise
        ``SignedInUserNotFoundError`` when no signed-in user has the ID.
        """
        ...


class V2UserInvitationResourceService(Protocol):
    """Route-independent email invitations and their acceptance."""

    def create_invitation(
        self, *, principal: AccountPrincipal, email: str, user_type: UserType
    ) -> AdminInvitationRead:
        """Invite an address to become an author or admin, then email it."""
        ...

    def list_invitations(
        self, *, principal: AccountPrincipal, search: AdminInvitationSearch
    ) -> AdminInvitationPage:
        """Return one page of open invitations, newest first, to an admin."""
        ...

    def resend_invitation(
        self, *, principal: AccountPrincipal, invitation_id: UUID
    ) -> AdminInvitationRead:
        """Give an open invitation a new link and expiry, and email it again.

        Raise ``InvitationNotFoundError`` unless an open invitation has the ID.
        """
        ...

    def revoke_invitation(
        self, *, principal: AccountPrincipal, invitation_id: UUID
    ) -> None:
        """Revoke an open invitation.

        Raise ``InvitationNotFoundError`` unless an open invitation has the ID.
        """
        ...

    def accept_invitation(
        self, *, principal: UserPrincipal, token: str, country_id: str
    ) -> InvitationAcceptance:
        """Accept an invitation for the signed-in user, giving its type.

        Raise one of the invitation acceptance errors, each with its ``code``,
        when it can't be accepted.
        """
        ...
