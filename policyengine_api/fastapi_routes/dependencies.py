"""Injectable dependencies for native FastAPI compatibility routes."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Annotated, Protocol

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from policyengine_api.fastapi_routes.metadata_protocols import (
    MetadataReader,
    V2MetadataResourceReader,
)
from policyengine_api.fastapi_routes.resource_service_protocols import (
    V2AccountResourceService,
    V2CountryResourceService,
    V2HouseholdCalculationResourceService,
    V2HouseholdResourceService,
    V2PolicyResourceService,
    V2UserHouseholdResourceService,
    V2UserInvitationResourceService,
    V2UserPolicyResourceService,
    V2UserReportResourceService,
    V2UserSimulationResourceService,
    V2UserTypeResourceService,
)
from policyengine_api.fastapi_routes.v2.metadata.response_cache_support import (
    MetadataResponseCache,
)
from policyengine_api.fastapi_routes.v2.user_auth_support import (
    authenticate_account_request,
    forwarded_user_credential,
)
from policyengine_api.libs.server_credentials import CallerKind
from policyengine_api.libs.user_auth import (
    FORWARDED_USER_AUTHORIZATION_HEADER,
    UNAUTHENTICATED_USER_HEADER,
    load_user_auth_settings,
)
from policyengine_api.readiness import is_ready
from policyengine_api.request_caller import current_request_caller
from policyengine_api.services.v2.metadata.process_state import (
    SelectedCatalogStore,
)
from policyengine_api.services.v2.user_types.types import UserProfileSource

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.services.v2.associations.types import (
        LegacyReferenceChecker,
    )
    from policyengine_api.services.v2.identity.types import (
        AccountPrincipal,
    )
    from policyengine_api.services.v2.user_emails.services import V2UserEmailService

__all__ = [
    "MetadataReader",
    "NativeRouteDependencies",
    "SimulationGatewayProbe",
    "V2AccountResourceService",
    "V2CountryResourceService",
    "V2HouseholdCalculationResourceService",
    "V2HouseholdResourceService",
    "V2MetadataResourceReader",
    "V2PolicyResourceService",
    "V2UserHouseholdResourceService",
    "V2UserInvitationResourceService",
    "V2UserPolicyResourceService",
    "V2UserReportResourceService",
    "V2UserSimulationResourceService",
    "V2UserTypeResourceService",
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


def _default_v2_household_calculation_service_factory() -> (
    V2HouseholdCalculationResourceService
):
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.libs.simulation_household_calculations import (
        process_simulation_household_calculation_client,
    )
    from policyengine_api.services.v2.household_calculations.database_session import (
        HouseholdCalculationDatabaseSession,
    )
    from policyengine_api.services.v2.household_calculations.services import (
        V2HouseholdCalculationService,
    )

    return V2HouseholdCalculationService(
        countries=_default_v2_country_service_factory(),
        households=_default_v2_household_service_factory(),
        policies=_default_v2_policy_service_factory(),
        database_session=HouseholdCalculationDatabaseSession(get_v2_session_factory()),
        simulation_factory=process_simulation_household_calculation_client,
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
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_user_bearer_scheme)
    ],
    unauthenticated_user: Annotated[str | None, Depends(_unauthenticated_user_scheme)],
) -> AccountPrincipal:
    """Authenticate the request's account; fails closed without a credential.

    When the credential check before routing found a server credential, the
    account is the user that server forwards (see ``user_auth_support``).
    """
    caller = current_request_caller()
    if caller is not None and caller.kind is CallerKind.SERVER:
        # Authorization carries the server's own token; the user is the one
        # the server forwards.
        user_authorization = forwarded_user_credential(
            request.headers.getlist(FORWARDED_USER_AUTHORIZATION_HEADER)
        )
    elif credentials is not None:
        user_authorization = f"Bearer {credentials.credentials}"
    else:
        user_authorization = None
    return authenticate_account_request(user_authorization, unauthenticated_user)


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


def _default_user_profile_source() -> UserProfileSource | None:
    """Return the users' Auth0 tenant to read admins' user profiles from.

    None without the AUTH0_USER_PROFILES_* settings. The users' issuer says
    which identities are that tenant's users; the settings are refused
    without it. Settings are read on each call, and raise when they are
    unusable.
    """
    from policyengine_api.libs.auth0_management import (
        build_auth0_user_profile_reader,
    )

    reader = build_auth0_user_profile_reader()
    if reader is None:
        return None
    return UserProfileSource(issuer=load_user_auth_settings().issuer, reader=reader)


def _default_user_email_service() -> V2UserEmailService:
    """Return the email service: Postmark, and the users' Auth0 tenant.

    Without the POSTMARK_* settings it sends nothing and records a WARNING
    for each email; settings are read when an email is sent.
    """
    from policyengine_api.libs.postmark_email import build_postmark_email_sender
    from policyengine_api.services.v2.user_emails.services import (
        V2UserEmailService,
    )

    return V2UserEmailService(
        email_sender_factory=build_postmark_email_sender,
        user_profile_source_factory=_default_user_profile_source,
    )


def _default_v2_user_type_service_factory() -> V2UserTypeResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.user_types.database_session import (
        UserTypeDatabaseSession,
    )
    from policyengine_api.services.v2.user_types.services import V2UserTypeService

    return V2UserTypeService(
        UserTypeDatabaseSession(get_v2_session_factory()),
        user_profile_source_factory=_default_user_profile_source,
        user_email_service=_default_user_email_service(),
    )


def _default_v2_user_invitation_service_factory() -> V2UserInvitationResourceService:
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.user_invitations.database_session import (
        UserInvitationDatabaseSession,
    )
    from policyengine_api.services.v2.user_invitations.services import (
        V2UserInvitationService,
    )

    return V2UserInvitationService(
        UserInvitationDatabaseSession(get_v2_session_factory()),
        user_email_service=_default_user_email_service(),
        user_profile_source_factory=_default_user_profile_source,
    )


@dataclass(frozen=True)
class NativeRouteDependencies:
    """Runtime collaborators for native read routes."""

    readiness_probe: Callable[[], bool]
    gateway_client_factory: Callable[[], SimulationGatewayProbe]
    metadata_reader_factory: Callable[[], MetadataReader]
    v2_metadata_reader_factory: Callable[[], V2MetadataResourceReader] | None = None
    v2_country_service_factory: Callable[[], V2CountryResourceService] | None = None
    v2_policy_service_factory: Callable[[], V2PolicyResourceService] | None = None
    v2_household_service_factory: Callable[[], V2HouseholdResourceService] | None = None
    v2_household_calculation_service_factory: (
        Callable[[], V2HouseholdCalculationResourceService] | None
    ) = None
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
    v2_user_type_service_factory: Callable[[], V2UserTypeResourceService] | None = None
    v2_user_invitation_service_factory: (
        Callable[[], V2UserInvitationResourceService] | None
    ) = None
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
            v2_metadata_reader_factory=_default_v2_metadata_reader_factory,
            v2_country_service_factory=_default_v2_country_service_factory,
            v2_metadata_response_cache=_process_metadata_response_cache(),
            v2_policy_service_factory=_default_v2_policy_service_factory,
            v2_household_service_factory=_default_v2_household_service_factory,
            v2_household_calculation_service_factory=(
                _default_v2_household_calculation_service_factory
            ),
            v2_user_policy_service_factory=(_default_v2_user_policy_service_factory),
            v2_user_household_service_factory=(
                _default_v2_user_household_service_factory
            ),
            v2_user_simulation_service_factory=(
                _default_v2_user_simulation_service_factory
            ),
            v2_user_report_service_factory=_default_v2_user_report_service_factory,
            v2_account_service_factory=_default_v2_account_service_factory,
            v2_user_type_service_factory=_default_v2_user_type_service_factory,
            v2_user_invitation_service_factory=(
                _default_v2_user_invitation_service_factory
            ),
            require_user=_default_require_user,
        )
