"""Interfaces of the v2 resource services that native FastAPI routes depend on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import UserType
    from policyengine_api.services.v2.countries.types import CountryRead
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
    from policyengine_api.services.v2.user_households.types import (
        UserHouseholdCreateFields,
        UserHouseholdFilter,
        UserHouseholdPage,
        UserHouseholdRead,
        UserHouseholdUpdateInput,
    )
    from policyengine_api.services.v2.user_policies.types import (
        UserPolicyCreateFields,
        UserPolicyFilter,
        UserPolicyPage,
        UserPolicyRead,
        UserPolicyUpdateInput,
    )
    from policyengine_api.services.v2.user_reports.types import (
        SharedUserReportRead,
        UserReportCreateFields,
        UserReportPage,
        UserReportRead,
        UserReportUpdateInput,
    )
    from policyengine_api.services.v2.user_simulations.types import (
        UserSimulationCreateFields,
        UserSimulationPage,
        UserSimulationRead,
        UserSimulationUpdateInput,
    )
    from policyengine_api.services.v2.user_types.types import (
        AdminUserPage,
        AdminUserRead,
        AdminUserSearch,
        UserTypeChangeRead,
    )


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
        household calculations, ``HouseholdNotFoundError`` or
        ``PolicyNotFoundError`` for a record not stored in that country,
        ``HouseholdCalculationYearError`` for a household without a default
        year, ``PolicyParametersMissingError`` for a policy setting parameters
        the running catalog version lacks, and the simulation service errors
        when it refuses the calculation.
        """
        ...

    def get_calculation(self, calculation_id: UUID) -> HouseholdCalculationRead:
        """Return the calculation household_jobs records.

        Raise ``HouseholdCalculationNotFoundError`` when there is no such job.
        """
        ...


class V2StoredReportResourceService(Protocol):
    """Route-independent report operations for one request."""

    def get_report(self, *, country_id: str, report_id: UUID) -> StoredReportRead:
        """Return the country's report, its newest run and that run's result.

        The report is an economy report, a household report or a budget
        window. Raise ``StoredReportNotFoundError`` when the country has no
        such report, and ``EconomyResultUnreadableError``,
        ``HouseholdResultUnreadableError`` or
        ``BudgetWindowResultUnreadableError`` when a succeeded run's result
        cannot be read.
        """
        ...

    def list_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> tuple[StoredReportSummaryRead, ...]:
        """Return the country's reports of every kind among those named, in order."""
        ...

    def create_report(self, report_input: ReportCreationInput) -> StoredReportRead:
        """Create the report through the simulation service; return it as stored.

        Raise ``EconomyCalculationsUnsupportedError`` for an economy report in
        a country without economy reports,
        ``HouseholdCalculationCountryError`` for a household report in a
        country without household calculations, ``HouseholdNotFoundError``
        for a household the country does not store,
        ``HouseholdCalculationYearError`` for one with no default year,
        ``PolicyNotFoundError``
        for a policy the country does not store,
        ``PolicyParametersMissingError`` for a policy that sets parameters the
        running catalog version lacks, ``SubmissionStorageError`` when the
        database or its catalog cannot be read for those checks, the
        simulation service's errors, and ``CreatedReportUnreadableError`` when
        the report it created cannot be read back.
        """
        ...

    def rerun_report(
        self, *, country_id: str, report_id: UUID, force: bool
    ) -> StoredReportRead:
        """Run the country's report again; return it with its new run as its newest.

        Raise ``StoredReportNotFoundError`` when the country has no such
        report; the errors of the country check a new report of its kind makes
        (economy calculations, or household calculations for a household
        report) and of the policy checks of its simulations, as
        ``create_report`` raises them (a household report's household is not
        checked again); the simulation service's errors, among them
        ``SimulationServiceConflictError`` when it will not run the report
        again now, and ``RerunReportUnreadableError`` when the report cannot
        be read back once its new run was started.
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
        simulation's one policy, and ``CreatedSimulationUnreadableError`` when
        the simulation it created cannot be read back.
        """
        ...


class V2UserPolicyResourceService(Protocol):
    """Route-independent user-policy operations for one request."""

    def create_user_policy(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserPolicyCreateFields,
    ) -> UserPolicyRead:
        """Save a policy for the caller, provisioning their user if needed."""
        ...

    def get_user_policy(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserPolicyRead:
        """Return the caller's association, or raise ``UserPolicyNotFoundError``."""
        ...

    def list_user_policies(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        policy_filter: UserPolicyFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserPolicyPage:
        """Return a page of the caller's associations, optionally for one policy."""
        ...

    def patch_user_policy(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserPolicyUpdateInput,
    ) -> UserPolicyRead:
        """Update the supplied fields of the caller's association and return it.

        The association keeps its id, owner and creation time. A new
        ``legacy_policy_id`` repoints it to another v1 policy; a new ``policy_id``
        repoints it to a v2 policy in the same country and, sent without
        ``legacy_policy_id``, clears the v1 reference.
        """
        ...

    def delete_user_policy(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete the caller's association, or raise ``UserPolicyNotFoundError``."""
        ...


class V2UserHouseholdResourceService(Protocol):
    """Route-independent user-household operations for one request."""

    def create_user_household(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserHouseholdCreateFields,
    ) -> UserHouseholdRead:
        """Save a household for the caller, provisioning their user if needed."""
        ...

    def get_user_household(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserHouseholdRead:
        """Return the caller's association, or raise ``UserHouseholdNotFoundError``."""
        ...

    def list_user_households(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        household_filter: UserHouseholdFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserHouseholdPage:
        """Return a page of the caller's associations, optionally for one household."""
        ...

    def patch_user_household(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserHouseholdUpdateInput,
    ) -> UserHouseholdRead:
        """Update the supplied fields of the caller's association and return it.

        The association keeps its id, owner and creation time. A new
        ``legacy_household_id`` repoints it to another v1 household; a new
        ``household_id`` repoints it to a v2 household in the same country and,
        sent without ``legacy_household_id``, clears the v1 reference.
        """
        ...

    def delete_user_household(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete the caller's association, or raise ``UserHouseholdNotFoundError``."""
        ...


class V2UserSimulationResourceService(Protocol):
    """Route-independent user-simulation operations for one request."""

    def create_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserSimulationCreateFields,
    ) -> UserSimulationRead:
        """Save a v1 simulation for the caller, provisioning their user if needed."""
        ...

    def get_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserSimulationRead:
        """Return the caller's association, or raise ``UserSimulationNotFoundError``."""
        ...

    def list_user_simulations(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        legacy_simulation_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserSimulationPage:
        """Return a page of the caller's associations, optionally for one simulation."""
        ...

    def patch_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserSimulationUpdateInput,
    ) -> UserSimulationRead:
        """Update the supplied fields of the caller's association and return it.

        A new ``legacy_simulation_id`` repoints it to another v1 simulation.
        """
        ...

    def delete_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete the caller's association, or raise ``UserSimulationNotFoundError``."""
        ...


class V2UserReportResourceService(Protocol):
    """Route-independent user-report operations for one request."""

    def create_user_report(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserReportCreateFields,
    ) -> UserReportRead:
        """Save a v1 report for the caller, provisioning their user if needed.

        Linked saved reforms must be the caller's own.
        """
        ...

    def get_user_report(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserReportRead:
        """Return the caller's association, or raise ``UserReportNotFoundError``."""
        ...

    def get_shared_user_report(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> SharedUserReportRead:
        """Return any user's saved report to a link holder, without its owner.

        Raise ``UserReportNotFoundError`` when the country has no such report.
        """
        ...

    def list_user_reports(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        legacy_report_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserReportPage:
        """Return a page of the caller's associations, optionally for one v1 report."""
        ...

    def patch_user_report(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserReportUpdateInput,
    ) -> UserReportRead:
        """Update the supplied fields of the caller's association and return it."""
        ...

    def delete_user_report(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete the caller's association, or raise ``UserReportNotFoundError``."""
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
