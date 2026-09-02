"""Injectable dependencies for native FastAPI compatibility routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from policyengine_api.json_types import JSONObject

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
    from policyengine_api.services.v2.user_policies.types import (
        UserPolicyCreationInput,
        UserPolicyPage,
        UserPolicyRead,
        UserPolicyUpdateInput,
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


class V2UserPolicyResourceService(Protocol):
    """Route-independent native association operations for one request."""

    def create_user_policy(
        self,
        association_input: "UserPolicyCreationInput",
    ) -> "UserPolicyRead": ...

    def get_user_policy(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> "UserPolicyRead": ...

    def list_user_policies(
        self,
        *,
        country_id: str,
        user_id: UUID,
        policy_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> "UserPolicyPage": ...

    def patch_user_policy(
        self,
        *,
        country_id: str,
        association_id: UUID,
        association_input: "UserPolicyUpdateInput",
    ) -> "UserPolicyRead": ...

    def delete_user_policy(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> None: ...


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


def _default_v2_user_policy_service_factory() -> V2UserPolicyResourceService:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.user_policies.database_session import (
        UserPolicyDatabaseSession,
    )
    from policyengine_api.services.v2.user_policies.services import (
        V2UserPolicyService,
    )

    return V2UserPolicyService(UserPolicyDatabaseSession(get_v2_session_factory()))


@dataclass(frozen=True)
class NativeRouteDependencies:
    """Runtime collaborators for native read routes."""

    readiness_probe: Callable[[], bool]
    gateway_client_factory: Callable[[], SimulationGatewayProbe]
    metadata_reader_factory: Callable[[], MetadataReader]
    specification_provider: Callable[[], JSONObject]
    v2_metadata_reader_factory: Callable[[], V2MetadataResourceReader] | None = None
    v2_policy_service_factory: Callable[[], V2PolicyResourceService] | None = None
    v2_user_policy_service_factory: Callable[[], V2UserPolicyResourceService] | None = (
        None
    )

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
            v2_user_policy_service_factory=(_default_v2_user_policy_service_factory),
        )
