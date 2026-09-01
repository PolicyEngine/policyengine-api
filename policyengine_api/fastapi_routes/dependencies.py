"""Injectable dependencies for native FastAPI compatibility routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata as importlib_metadata
from typing import Protocol

from policyengine_api.json_types import JSONObject


class MetadataReader(Protocol):
    """Read the already-loaded metadata document for a country."""

    def get_metadata(self, country_id: str) -> JSONObject: ...


class V2MetadataResourceReader(Protocol):
    """Own the database session used by one v2 metadata resource request."""

    def close(self) -> None: ...


class V2PolicyResourceService(Protocol):
    """Route-independent native policy operations for one request."""

    def create_policy(self, command: object) -> object: ...

    def get_policy(self, *, country_id: str, policy_id: object) -> object: ...

    def list_policies(self, **filters: object) -> object: ...


class V2UserPolicyResourceService(Protocol):
    """Route-independent native association operations for one request."""

    def create_user_policy(self, command: object) -> object: ...

    def get_user_policy(self, **identity: object) -> object: ...

    def list_user_policies(self, **filters: object) -> object: ...

    def patch_user_policy(self, **changes: object) -> object: ...

    def delete_user_policy(self, **identity: object) -> None: ...


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
    from policyengine_api.services.v2.metadata_service import V2MetadataService

    return V2MetadataService(
        get_v2_session_factory()(),
        running_policyengine_version=_running_policyengine_version(),
    )


def _default_v2_policy_service_factory() -> V2PolicyResourceService:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.policy_service import V2PolicyService

    return V2PolicyService(
        get_v2_session_factory(),
        running_policyengine_version=_running_policyengine_version(),
    )


def _default_v2_user_policy_service_factory() -> V2UserPolicyResourceService:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.user_policy_service import V2UserPolicyService

    return V2UserPolicyService(get_v2_session_factory())


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
