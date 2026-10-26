"""Injectable dependencies for native FastAPI compatibility routes."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Annotated, Protocol

from fastapi import Depends
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
    MetadataResponseCache,
)
from policyengine_api.fastapi_routes.v2.user_auth import authenticate_account_request
from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER
from policyengine_api.readiness import is_ready
from policyengine_api.services.v2.metadata.selected_catalogs import (
    SelectedCatalogStore,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from uuid import UUID

    from policyengine_api.json_types import JSONObject
    from policyengine_api.services.v2.associations.types import (
        LegacyReferenceChecker,
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
    from policyengine_api.services.v2.metadata.types import (
        MetadataCanonicalParameterValue,
        MetadataCatalogParametersResult,
        MetadataCatalogVariablesResult,
        MetadataDataset,
        MetadataDetailResult,
        MetadataEconomyOptionsResult,
        MetadataModel,
        MetadataModelCatalogResult,
        MetadataModelSelectionResult,
        MetadataModelVersionDetail,
        MetadataPageResult,
        MetadataParameterChild,
        MetadataParameterSearchFile,
        MetadataParameterSummary,
        MetadataRegion,
        MetadataVariable,
        ParameterFilter,
        ParameterTreeLevel,
        ParameterValueFilter,
    )
    from policyengine_api.services.v2.policies.types import (
        NativePolicyCreation,
        NativePolicyCreationInput,
        PolicyPage,
        PolicyRead,
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


class MetadataReader(Protocol):
    """Read the already-loaded metadata document for a country."""

    def get_metadata(self, country_id: str) -> JSONObject:
        """Return the loaded v1 metadata document for a supported country."""
        ...


class V2MetadataResourceReader(Protocol):
    """Own the database session used by one v2 metadata resource request.

    Every read selects one country catalog: the one published for
    ``policyengine_version``, or the running package's catalog when it is None.
    Absent resources raise ``MetadataResourceNotFoundError``, and list reads
    raise ``InvalidMetadataPageError`` unless ``offset >= 0`` and
    ``1 <= limit <= 500``.
    """

    def close(self) -> None:
        """Release the request's database session, even after a failed read."""
        ...

    def list_models(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModel]:
        """Return a page holding the selected catalog's single tax-benefit model."""
        ...

    def get_model(
        self,
        country_id: str,
        model_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModel]:
        """Return the selected catalog's model when ``model_id`` is its UUID."""
        ...

    def get_model_by_country(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelSelectionResult:
        """Return the country's model and the selected catalog's model version."""
        ...

    def list_model_versions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModelVersionDetail]:
        """Return a page holding the selected catalog's single model version."""
        ...

    def get_model_version(
        self,
        country_id: str,
        version_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModelVersionDetail]:
        """Return the selected model version when ``version_id`` is its UUID."""
        ...

    def list_variables(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> MetadataPageResult[MetadataVariable]:
        """Return variables in name order, optionally filtered by ``search``.

        ``search`` is a case-insensitive substring of the name, label or description.
        """
        ...

    def get_variable(
        self,
        country_id: str,
        variable_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataVariable]:
        """Return one variable of the selected catalog by UUID."""
        ...

    def list_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        parameter_filter: ParameterFilter | None = None,
    ) -> MetadataPageResult[MetadataParameterSummary]:
        """Return parameters in name order, optionally filtered.

        The filter's ``search`` is a case-insensitive substring of the name,
        label or description; its ``names`` keep only those exact names.
        """
        ...

    def get_parameter(
        self,
        country_id: str,
        parameter_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataParameterSummary]:
        """Return one parameter of the selected catalog by UUID."""
        ...

    def list_parameter_children(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        level: ParameterTreeLevel | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataParameterChild]:
        """Return the nodes and parameters one level below the level's parent path.

        An empty parent path lists the top level of the parameter tree; the
        level's ``reform_changeable`` keeps only what a reform can change.
        """
        ...

    def get_parameter_search_file(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataParameterSearchFile:
        """Return the selected catalog version's stored parameter search file.

        Raise ``ParameterSearchFileUnavailableError`` when the version has none.
        """
        ...

    def list_parameter_values(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        value_filter: ParameterValueFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataCanonicalParameterValue]:
        """Return canonical values, optionally for one or several parameters.

        The filter's ``parameter_id`` or ``parameter_names`` select parameters.
        With its ``current``, only values in effect on the UTC day of its
        ``now`` (default: the present) are returned.
        """
        ...

    def get_parameter_value(
        self,
        country_id: str,
        value_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataCanonicalParameterValue]:
        """Return one canonical parameter value of the selected catalog by UUID."""
        ...

    def list_datasets(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataDataset]:
        """Return the logical input datasets of the selected catalog."""
        ...

    def get_dataset(
        self,
        country_id: str,
        dataset_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataDataset]:
        """Return one logical input dataset of the selected catalog by UUID."""
        ...

    def list_regions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        region_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataRegion]:
        """Return the catalog's regions by code, optionally of one ``region_type``."""
        ...

    def get_region(
        self,
        country_id: str,
        region_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        """Return one region of the selected catalog by UUID."""
        ...

    def get_region_by_code(
        self,
        country_id: str,
        region_code: str,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        """Return one region by code; the national region's code is the country id."""
        ...

    def get_economy_options(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataEconomyOptionsResult:
        """Return the options a client needs to configure an economy comparison.

        These are the current-law policy id, regions, years and datasets.

        Raise ``MetadataCatalogUnavailableError`` when the national region, its
        dataset or the model version's options are missing from the catalog.
        """
        ...

    def get_model_catalog(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelCatalogResult:
        """Return the small parts of the selected catalog version.

        These are the model and model version, entities, basic inputs, regions,
        logical input datasets and economy choices, which are empty for a
        catalog without regions. Raise ``MetadataCatalogUnavailableError`` when
        a catalog with regions lacks what ``get_economy_options`` needs.
        """
        ...

    def get_catalog_variables(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataCatalogVariablesResult:
        """Return every variable of the selected catalog version, in name order.

        It also carries the current-law values of each parameter a variable's
        adds or subtracts names.
        """
        ...

    def get_catalog_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        names: Sequence[str],
    ) -> MetadataCatalogParametersResult:
        """Return the named parameters of the selected version, in name order.

        Each carries its current-law values; the result also carries the
        stored labels of their ancestor nodes and the names the version lacks.
        """
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

    def get_policy(self, *, country_id: str, policy_id: UUID) -> PolicyRead:
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
    ) -> PolicyPage:
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


class SimulationGatewayProbe(Protocol):
    """Minimal simulation-entrypoint health-check interface."""

    def health_check(self) -> bool:
        """Return whether the simulation entrypoint's health endpoint returns 200."""
        ...


def _default_readiness_probe() -> bool:
    return is_ready()


def _default_gateway_client_factory() -> SimulationGatewayProbe:
    from policyengine_api.libs.simulation_entrypoint import (  # noqa: PLC0415  # builds its client at import, which needs the gateway URL configured
        SimulationEntrypointClient,
    )

    return SimulationEntrypointClient()


def _default_metadata_reader_factory() -> MetadataReader:
    from policyengine_api.services.metadata_service import (  # noqa: PLC0415  # loads every country model; only the default reader needs it
        MetadataService,
    )

    return MetadataService()


def _default_specification_provider() -> JSONObject:
    from policyengine_api.specification import (  # noqa: PLC0415  # reads and builds the OpenAPI document at import
        OPENAPI_SPECIFICATION,
    )

    return OPENAPI_SPECIFICATION


@lru_cache(maxsize=1)
def _running_policyengine_version() -> str:
    return importlib_metadata.version("policyengine")


@lru_cache(maxsize=1)
def _process_selected_catalogs() -> SelectedCatalogStore:
    """Return the catalog versions this process's metadata reads have selected."""
    return SelectedCatalogStore()


@lru_cache(maxsize=1)
def _process_metadata_response_cache() -> MetadataResponseCache:
    """Return the whole catalog-version responses this process keeps."""
    return MetadataResponseCache()


def _default_v2_metadata_reader_factory() -> V2MetadataResourceReader:
    from policyengine_api.data.v2.database import (
        get_v2_read_session_factory,
    )
    from policyengine_api.services.v2.metadata.database_session import (
        MetadataDatabaseSession,
    )
    from policyengine_api.services.v2.metadata.services import V2MetadataService

    return V2MetadataService(
        MetadataDatabaseSession(get_v2_read_session_factory()()),
        running_policyengine_version=_running_policyengine_version(),
        selected_catalogs=_process_selected_catalogs(),
    )


def _default_v2_policy_service_factory() -> V2PolicyResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.policies.database_session import (
        PolicyDatabaseSession,
    )
    from policyengine_api.services.v2.policies.services import V2PolicyService

    return V2PolicyService(
        PolicyDatabaseSession(get_v2_session_factory()),
        running_policyengine_version=_running_policyengine_version(),
    )


def _default_v2_household_service_factory() -> V2HouseholdResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.households.database_session import (
        HouseholdDatabaseSession,
    )
    from policyengine_api.services.v2.households.services import V2HouseholdService

    return V2HouseholdService(
        HouseholdDatabaseSession(get_v2_session_factory()),
    )


_user_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="UserAccessToken",
    description="Auth0 user access token issued for the Public API audience.",
)
_unauthenticated_user_scheme = APIKeyHeader(
    name=UNAUTHENTICATED_USER_HEADER,
    auto_error=False,
    scheme_name="UnauthenticatedUser",
    description=(
        "Canonical UUID that a signed-out browser generates once and keeps. It "
        "is a bearer credential for that browser's unauthenticated user; "
        "ignored when a bearer access token is present."
    ),
)


def _default_require_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_user_bearer_scheme)
    ],
    unauthenticated_user: Annotated[str | None, Depends(_unauthenticated_user_scheme)],
) -> AccountPrincipal:
    """Authenticate the request's account; fails closed without a credential."""
    return authenticate_account_request(
        None if credentials is None else f"Bearer {credentials.credentials}",
        unauthenticated_user,
    )


def _build_v1_legacy_reference_service() -> LegacyReferenceChecker:
    from policyengine_api.data.orm import (  # noqa: PLC0415  # looked up per call, so tests can replace the v1 session factory
        get_v1_session_factory,
    )
    from policyengine_api.services.v2.legacy_refs.database_session import (
        LegacyReferenceDatabaseSession,
    )
    from policyengine_api.services.v2.legacy_refs.services import (
        V1LegacyReferenceService,
    )

    return V1LegacyReferenceService(
        LegacyReferenceDatabaseSession(get_v1_session_factory())
    )


def _default_legacy_reference_checker() -> LegacyReferenceChecker:
    """Defer the v1 session factory until a request checks a v1 reference."""
    from policyengine_api.services.v2.legacy_refs.services import (
        DeferredLegacyReferenceService,
    )

    return DeferredLegacyReferenceService(_build_v1_legacy_reference_service)


def _default_v2_user_policy_service_factory() -> V2UserPolicyResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.user_policies.database_session import (
        UserPolicyDatabaseSession,
    )
    from policyengine_api.services.v2.user_policies.services import V2UserPolicyService

    return V2UserPolicyService(
        UserPolicyDatabaseSession(get_v2_session_factory()),
        _default_legacy_reference_checker(),
    )


def _default_v2_user_household_service_factory() -> V2UserHouseholdResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.user_households.database_session import (
        UserHouseholdDatabaseSession,
    )
    from policyengine_api.services.v2.user_households.services import (
        V2UserHouseholdService,
    )

    return V2UserHouseholdService(
        UserHouseholdDatabaseSession(get_v2_session_factory()),
        _default_legacy_reference_checker(),
    )


def _default_v2_user_simulation_service_factory() -> V2UserSimulationResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.user_simulations.database_session import (
        UserSimulationDatabaseSession,
    )
    from policyengine_api.services.v2.user_simulations.services import (
        V2UserSimulationService,
    )

    return V2UserSimulationService(
        UserSimulationDatabaseSession(get_v2_session_factory()),
        _default_legacy_reference_checker(),
    )


def _default_v2_user_report_service_factory() -> V2UserReportResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.user_reports.database_session import (
        UserReportDatabaseSession,
    )
    from policyengine_api.services.v2.user_reports.services import V2UserReportService

    return V2UserReportService(
        UserReportDatabaseSession(get_v2_session_factory()),
        _default_legacy_reference_checker(),
    )


def _default_v2_account_service_factory() -> V2AccountResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.libs.auth0_management import (
        build_auth0_user_deleter,
    )
    from policyengine_api.services.v2.user_accounts.database_session import (
        AccountDatabaseSession,
    )
    from policyengine_api.services.v2.user_accounts.services import V2AccountService

    return V2AccountService(
        AccountDatabaseSession(get_v2_session_factory()),
        auth0_user_deleter_factory=build_auth0_user_deleter,
    )


@dataclass(frozen=True)
class NativeRouteDependencies:
    """Runtime collaborators for native read routes."""

    readiness_probe: Callable[[], bool]
    gateway_client_factory: Callable[[], SimulationGatewayProbe]
    metadata_reader_factory: Callable[[], MetadataReader]
    specification_provider: Callable[[], JSONObject]
    v2_metadata_reader_factory: Callable[[], V2MetadataResourceReader] | None = None
    v2_policy_service_factory: Callable[[], V2PolicyResourceService] | None = None
    v2_household_service_factory: Callable[[], V2HouseholdResourceService] | None = None
    v2_user_policy_service_factory: Callable[[], V2UserPolicyResourceService] | None = (
        None
    )
    v2_user_household_service_factory: (
        Callable[[], V2UserHouseholdResourceService] | None
    ) = None
    v2_user_simulation_service_factory: (
        Callable[[], V2UserSimulationResourceService] | None
    ) = None
    v2_user_report_service_factory: Callable[[], V2UserReportResourceService] | None = (
        None
    )
    v2_account_service_factory: Callable[[], V2AccountResourceService] | None = None
    # Whole catalog-version responses (/v2/model-catalog and its variables) are
    # kept here once built; None reads them on every request.
    v2_metadata_response_cache: MetadataResponseCache | None = None
    # User-owned routes attach this at router level. The default validates the
    # Auth0 bearer token, or else accepts the unauthenticated-user header, and
    # fails closed (401/403/503); tests replace it with a callable returning a
    # fixed principal.
    require_user: Callable[..., AccountPrincipal] = _default_require_user

    @classmethod
    def defaults(cls) -> NativeRouteDependencies:
        """Build lazy defaults without importing country models unnecessarily."""
        return cls(
            readiness_probe=_default_readiness_probe,
            gateway_client_factory=_default_gateway_client_factory,
            metadata_reader_factory=_default_metadata_reader_factory,
            specification_provider=_default_specification_provider,
            v2_metadata_reader_factory=_default_v2_metadata_reader_factory,
            v2_metadata_response_cache=_process_metadata_response_cache(),
            v2_policy_service_factory=_default_v2_policy_service_factory,
            v2_household_service_factory=_default_v2_household_service_factory,
            v2_user_policy_service_factory=(_default_v2_user_policy_service_factory),
            v2_user_household_service_factory=(
                _default_v2_user_household_service_factory
            ),
            v2_user_simulation_service_factory=(
                _default_v2_user_simulation_service_factory
            ),
            v2_user_report_service_factory=_default_v2_user_report_service_factory,
            v2_account_service_factory=_default_v2_account_service_factory,
            require_user=_default_require_user,
        )
