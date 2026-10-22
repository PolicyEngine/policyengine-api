"""Injectable dependencies for native FastAPI compatibility routes."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Annotated, Protocol

from fastapi import Depends
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from policyengine_api.fastapi_routes.metadata_protocols import (
    MetadataReader,
    V2MetadataResourceReader,
)
from policyengine_api.fastapi_routes.resource_service_protocols import (
    V2AccountResourceService,
    V2CountryResourceService,
    V2HouseholdResourceService,
    V2PolicyResourceService,
    V2UserHouseholdResourceService,
    V2UserPolicyResourceService,
    V2UserReportResourceService,
    V2UserSimulationResourceService,
)
from policyengine_api.fastapi_routes.v2.user_auth import authenticate_account_request
from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER
from policyengine_api.readiness import is_ready

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.json_types import JSONObject
    from policyengine_api.services.v2.associations.types import (
        LegacyReferenceChecker,
    )
    from policyengine_api.services.v2.identity.types import (
        AccountPrincipal,
    )

__all__ = [
    "MetadataReader",
    "NativeRouteDependencies",
    "SimulationGatewayProbe",
    "V2AccountResourceService",
    "V2CountryResourceService",
    "V2HouseholdResourceService",
    "V2MetadataResourceReader",
    "V2PolicyResourceService",
    "V2UserHouseholdResourceService",
    "V2UserPolicyResourceService",
    "V2UserReportResourceService",
    "V2UserSimulationResourceService",
]


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


def _default_v2_metadata_reader_factory() -> V2MetadataResourceReader:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.metadata.database_session import (
        MetadataDatabaseSession,
    )
    from policyengine_api.services.v2.metadata.services import V2MetadataService

    return V2MetadataService(
        MetadataDatabaseSession(get_v2_session_factory()()),
        running_policyengine_version=_running_policyengine_version(),
    )


def _default_v2_country_service_factory() -> V2CountryResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.countries.database_session import (
        CountryDatabaseSession,
    )
    from policyengine_api.services.v2.countries.services import V2CountryService

    return V2CountryService(CountryDatabaseSession(get_v2_session_factory()))


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
    v2_country_service_factory: Callable[[], V2CountryResourceService] | None = None
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
            v2_country_service_factory=_default_v2_country_service_factory,
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
