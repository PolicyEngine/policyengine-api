"""Injectable dependencies for native FastAPI compatibility routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fastapi import Depends
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from policyengine_api.json_types import JSONObject
from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER

if TYPE_CHECKING:
    from policyengine_api.services.v2.metadata.types import (
        MetadataCanonicalParameterValue,
        MetadataDataset,
        MetadataDetailResult,
        MetadataEconomyOptionsResult,
        MetadataModel,
        MetadataModelSelectionResult,
        MetadataModelVersionDetail,
        MetadataPageResult,
        MetadataParameterChild,
        MetadataParameterSummary,
        MetadataRegion,
        MetadataVariable,
    )
    from policyengine_api.services.v2.policies.types import (
        NativePolicyCreation,
        NativePolicyCreationInput,
        PolicyPage,
        PolicyRead,
    )
    from policyengine_api.services.v2.households.types import (
        HouseholdPage,
        HouseholdRead,
        NativeHouseholdCreation,
        NativeHouseholdCreationInput,
    )
    from policyengine_api.services.v2.associations.types import (
        LegacyReferenceChecker,
    )
    from policyengine_api.services.v2.identity.types import (
        AccountPrincipal,
        UserPrincipal,
    )
    from policyengine_api.services.v2.user_accounts.types import (
        AccountDeletion,
        AccountExport,
        AccountRead,
        AccountUpdateInput,
        AccountUpgrade,
    )
    from policyengine_api.services.v2.user_policies.types import (
        UserPolicyCreateFields,
        UserPolicyPage,
        UserPolicyRead,
        UserPolicyUpdateInput,
    )
    from policyengine_api.services.v2.user_households.types import (
        UserHouseholdCreateFields,
        UserHouseholdPage,
        UserHouseholdRead,
        UserHouseholdUpdateInput,
    )
    from policyengine_api.services.v2.user_reports.types import (
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

    def get_metadata(self, country_id: str) -> JSONObject: ...


class V2MetadataResourceReader(Protocol):
    """Own the database session used by one v2 metadata resource request."""

    def close(self) -> None: ...

    def list_models(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> "MetadataPageResult[MetadataModel]": ...

    def get_model(
        self,
        country_id: str,
        model_id: UUID,
        policyengine_version: str | None = None,
    ) -> "MetadataDetailResult[MetadataModel]": ...

    def get_model_by_country(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> "MetadataModelSelectionResult": ...

    def list_model_versions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> "MetadataPageResult[MetadataModelVersionDetail]": ...

    def get_model_version(
        self,
        country_id: str,
        version_id: UUID,
        policyengine_version: str | None = None,
    ) -> "MetadataDetailResult[MetadataModelVersionDetail]": ...

    def list_variables(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> "MetadataPageResult[MetadataVariable]": ...

    def get_variable(
        self,
        country_id: str,
        variable_id: UUID,
        policyengine_version: str | None = None,
    ) -> "MetadataDetailResult[MetadataVariable]": ...

    def list_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> "MetadataPageResult[MetadataParameterSummary]": ...

    def get_parameter(
        self,
        country_id: str,
        parameter_id: UUID,
        policyengine_version: str | None = None,
    ) -> "MetadataDetailResult[MetadataParameterSummary]": ...

    def list_parameter_children(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        parent_path: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> "MetadataPageResult[MetadataParameterChild]": ...

    def list_parameter_values(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        parameter_id: UUID | None = None,
        current: bool = False,
        offset: int = 0,
        limit: int = 100,
        now: datetime | None = None,
    ) -> "MetadataPageResult[MetadataCanonicalParameterValue]": ...

    def get_parameter_value(
        self,
        country_id: str,
        value_id: UUID,
        policyengine_version: str | None = None,
    ) -> "MetadataDetailResult[MetadataCanonicalParameterValue]": ...

    def list_datasets(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> "MetadataPageResult[MetadataDataset]": ...

    def get_dataset(
        self,
        country_id: str,
        dataset_id: UUID,
        policyengine_version: str | None = None,
    ) -> "MetadataDetailResult[MetadataDataset]": ...

    def list_regions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        region_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> "MetadataPageResult[MetadataRegion]": ...

    def get_region(
        self,
        country_id: str,
        region_id: UUID,
        policyengine_version: str | None = None,
    ) -> "MetadataDetailResult[MetadataRegion]": ...

    def get_region_by_code(
        self,
        country_id: str,
        region_code: str,
        policyengine_version: str | None = None,
    ) -> "MetadataDetailResult[MetadataRegion]": ...

    def get_economy_options(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> "MetadataEconomyOptionsResult": ...


class V2PolicyResourceService(Protocol):
    """Route-independent native policy operations for one request."""

    def create_policy(
        self,
        command: "NativePolicyCreationInput",
    ) -> "NativePolicyCreation": ...

    def get_policy(self, *, country_id: str, policy_id: UUID) -> "PolicyRead": ...

    def list_policies(
        self,
        *,
        country_id: str,
        tax_benefit_model_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> "PolicyPage": ...


class V2HouseholdResourceService(Protocol):
    """Route-independent native household operations for one request."""

    def create_household(
        self,
        household_input: "NativeHouseholdCreationInput",
    ) -> "NativeHouseholdCreation": ...

    def get_household(
        self,
        *,
        country_id: str,
        household_id: UUID,
    ) -> "HouseholdRead": ...

    def list_households(
        self,
        *,
        country_id: str,
        default_year: int | None,
        offset: int,
        limit: int,
    ) -> "HouseholdPage": ...


class V2UserPolicyResourceService(Protocol):
    """Route-independent user-policy operations for one request."""

    def create_user_policy(
        self,
        *,
        principal: "AccountPrincipal",
        association_input: "UserPolicyCreateFields",
    ) -> "UserPolicyRead": ...

    def get_user_policy(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
    ) -> "UserPolicyRead": ...

    def list_user_policies(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        policy_id: UUID | None = None,
        legacy_policy_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> "UserPolicyPage": ...

    def patch_user_policy(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
        association_input: "UserPolicyUpdateInput",
    ) -> "UserPolicyRead": ...

    def delete_user_policy(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
    ) -> None: ...


class V2UserHouseholdResourceService(Protocol):
    """Route-independent user-household operations for one request."""

    def create_user_household(
        self,
        *,
        principal: "AccountPrincipal",
        association_input: "UserHouseholdCreateFields",
    ) -> "UserHouseholdRead": ...

    def get_user_household(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
    ) -> "UserHouseholdRead": ...

    def list_user_households(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        household_id: UUID | None = None,
        legacy_household_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> "UserHouseholdPage": ...

    def patch_user_household(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
        association_input: "UserHouseholdUpdateInput",
    ) -> "UserHouseholdRead": ...

    def delete_user_household(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
    ) -> None: ...


class V2UserSimulationResourceService(Protocol):
    """Route-independent user-simulation operations for one request."""

    def create_user_simulation(
        self,
        *,
        principal: "AccountPrincipal",
        association_input: "UserSimulationCreateFields",
    ) -> "UserSimulationRead": ...

    def get_user_simulation(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
    ) -> "UserSimulationRead": ...

    def list_user_simulations(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        legacy_simulation_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> "UserSimulationPage": ...

    def patch_user_simulation(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
        association_input: "UserSimulationUpdateInput",
    ) -> "UserSimulationRead": ...

    def delete_user_simulation(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
    ) -> None: ...


class V2UserReportResourceService(Protocol):
    """Route-independent user-report operations for one request."""

    def create_user_report(
        self,
        *,
        principal: "AccountPrincipal",
        association_input: "UserReportCreateFields",
    ) -> "UserReportRead": ...

    def get_user_report(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
    ) -> "UserReportRead": ...

    def list_user_reports(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        legacy_report_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> "UserReportPage": ...

    def patch_user_report(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
        association_input: "UserReportUpdateInput",
    ) -> "UserReportRead": ...

    def delete_user_report(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        association_id: UUID,
    ) -> None: ...


class V2AccountResourceService(Protocol):
    """Route-independent account operations for one request."""

    def get_account(
        self, *, principal: "AccountPrincipal", country_id: str
    ) -> "AccountRead": ...

    def update_account(
        self,
        *,
        principal: "AccountPrincipal",
        country_id: str,
        account_input: "AccountUpdateInput",
    ) -> "AccountRead": ...

    def export_account(
        self, *, principal: "AccountPrincipal", country_id: str
    ) -> "AccountExport": ...

    def upgrade_account(
        self,
        *,
        principal: "UserPrincipal",
        unauthenticated_user_id: UUID,
        country_id: str,
    ) -> "AccountUpgrade": ...

    def delete_account(self, *, principal: "AccountPrincipal") -> "AccountDeletion": ...


class SimulationGatewayProbe(Protocol):
    """Minimal simulation-entrypoint health-check interface."""

    def health_check(self) -> bool: ...


def _default_readiness_probe() -> bool:
    from policyengine_api.readiness import is_ready

    return is_ready()


def _default_gateway_client_factory() -> SimulationGatewayProbe:
    from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient

    return SimulationEntrypointClient()


def _default_metadata_reader_factory() -> MetadataReader:
    from policyengine_api.services.metadata_service import MetadataService

    return MetadataService()


def _default_specification_provider() -> JSONObject:
    from policyengine_api.specification import OPENAPI_SPECIFICATION

    return OPENAPI_SPECIFICATION


@lru_cache(maxsize=1)
def _running_policyengine_version() -> str:
    return importlib_metadata.version("policyengine")


def _default_v2_metadata_reader_factory() -> V2MetadataResourceReader:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.metadata.database_session import (
        MetadataDatabaseSession,
    )
    from policyengine_api.services.v2.metadata.services import V2MetadataService

    return V2MetadataService(
        MetadataDatabaseSession(get_v2_session_factory()()),
        running_policyengine_version=_running_policyengine_version(),
    )


def _default_v2_policy_service_factory() -> V2PolicyResourceService:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.policies.database_session import (
        PolicyDatabaseSession,
    )
    from policyengine_api.services.v2.policies.services import V2PolicyService

    return V2PolicyService(
        PolicyDatabaseSession(get_v2_session_factory()),
        running_policyengine_version=_running_policyengine_version(),
    )


def _default_v2_household_service_factory() -> V2HouseholdResourceService:
    from policyengine_api.data.v2.database import get_v2_session_factory
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
    credentials: HTTPAuthorizationCredentials | None = Depends(_user_bearer_scheme),
    unauthenticated_user: str | None = Depends(_unauthenticated_user_scheme),
) -> "AccountPrincipal":
    """Authenticate the request's account; fails closed without a credential."""

    from policyengine_api.fastapi_routes.v2.user_auth import (
        authenticate_account_request,
    )

    return authenticate_account_request(
        None if credentials is None else f"Bearer {credentials.credentials}",
        unauthenticated_user,
    )


def _build_v1_legacy_reference_service() -> "LegacyReferenceChecker":
    from policyengine_api.data.orm import get_v1_session_factory
    from policyengine_api.services.v2.legacy_refs.database_session import (
        LegacyReferenceDatabaseSession,
    )
    from policyengine_api.services.v2.legacy_refs.services import (
        V1LegacyReferenceService,
    )

    return V1LegacyReferenceService(
        LegacyReferenceDatabaseSession(get_v1_session_factory())
    )


def _default_legacy_reference_checker() -> "LegacyReferenceChecker":
    """Defer the v1 session factory until a request checks a v1 reference."""

    from policyengine_api.services.v2.legacy_refs.services import (
        DeferredLegacyReferenceService,
    )

    return DeferredLegacyReferenceService(_build_v1_legacy_reference_service)


def _default_v2_user_policy_service_factory() -> V2UserPolicyResourceService:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.user_policies.database_session import (
        UserPolicyDatabaseSession,
    )
    from policyengine_api.services.v2.user_policies.services import (
        V2UserPolicyService,
    )

    return V2UserPolicyService(
        UserPolicyDatabaseSession(get_v2_session_factory()),
        _default_legacy_reference_checker(),
    )


def _default_v2_user_household_service_factory() -> V2UserHouseholdResourceService:
    from policyengine_api.data.v2.database import get_v2_session_factory
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
    from policyengine_api.data.v2.database import get_v2_session_factory
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
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.user_reports.database_session import (
        UserReportDatabaseSession,
    )
    from policyengine_api.services.v2.user_reports.services import (
        V2UserReportService,
    )

    return V2UserReportService(
        UserReportDatabaseSession(get_v2_session_factory()),
        _default_legacy_reference_checker(),
    )


def _default_v2_account_service_factory() -> V2AccountResourceService:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.libs.auth0_management import build_auth0_user_deleter
    from policyengine_api.services.v2.user_accounts.database_session import (
        AccountDatabaseSession,
    )
    from policyengine_api.services.v2.user_accounts.services import (
        V2AccountService,
    )

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
    # User-owned routes attach this at router level. The default validates the
    # Auth0 bearer token, or else accepts the unauthenticated-user header, and
    # fails closed (401/403/503); tests replace it with a callable returning a
    # fixed principal.
    require_user: Callable[..., "AccountPrincipal"] = _default_require_user

    @classmethod
    def defaults(cls) -> "NativeRouteDependencies":
        """Build lazy defaults without importing country models unnecessarily."""
        return cls(
            readiness_probe=_default_readiness_probe,
            gateway_client_factory=_default_gateway_client_factory,
            metadata_reader_factory=_default_metadata_reader_factory,
            specification_provider=_default_specification_provider,
            v2_metadata_reader_factory=_default_v2_metadata_reader_factory,
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
