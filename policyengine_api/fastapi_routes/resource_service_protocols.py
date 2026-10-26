"""Interfaces of the v2 resource services that native FastAPI routes depend on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

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

        A new ``legacy_policy_id`` repoints it to another v1 policy.
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

        A new ``legacy_household_id`` repoints it to another v1 household.
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
