"""Interfaces of the services behind users' saved items, which native routes call.

Saved policies, dynamics, households, simulations and reports.
``policyengine_api.fastapi_routes.resource_service_protocols`` re-exports
them, and routes and tests import them from there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.user_dynamics.types import (
        UserDynamicCreateFields,
        UserDynamicFilter,
        UserDynamicPage,
        UserDynamicRead,
        UserDynamicUpdateInput,
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


class V2UserDynamicResourceService(Protocol):
    """Route-independent saved-dynamic operations for one request."""

    def create_user_dynamic(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserDynamicCreateFields,
    ) -> UserDynamicRead:
        """Save a dynamic for the caller, provisioning their user if needed."""
        ...

    def get_user_dynamic(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserDynamicRead:
        """Return the caller's saved dynamic, or raise ``UserDynamicNotFoundError``."""
        ...

    def list_user_dynamics(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        dynamic_filter: UserDynamicFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserDynamicPage:
        """Return a page of the caller's saved dynamics, optionally for one dynamic."""
        ...

    def patch_user_dynamic(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserDynamicUpdateInput,
    ) -> UserDynamicRead:
        """Rename the caller's saved dynamic, or repoint it to another dynamic.

        It keeps its id, owner and creation time; a new ``dynamic_id`` must be
        stored in the same country.
        """
        ...

    def delete_user_dynamic(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete the caller's saved dynamic, or raise ``UserDynamicNotFoundError``."""
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
