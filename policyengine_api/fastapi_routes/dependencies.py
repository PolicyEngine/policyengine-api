"""Injectable dependencies for native FastAPI compatibility routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata as importlib_metadata
from typing import Protocol

from policyengine_api.data.v2.catalog.schemas import MetadataResult
from policyengine_api.json_types import JSONObject


class MetadataReader(Protocol):
    """Read the already-loaded metadata document for a country."""

    def get_metadata(self, country_id: str) -> JSONObject: ...


class V2MetadataReader(Protocol):
    """Read one already-initialized v2 metadata catalog."""

    def get_metadata(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataResult: ...

    def close(self) -> None: ...


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


def _default_v2_metadata_reader_factory() -> V2MetadataReader:
    from policyengine_api.data.v2.catalog.query import V2MetadataQueryService
    from policyengine_api.data.v2.database import get_v2_session_factory

    return V2MetadataQueryService(
        get_v2_session_factory()(),
        running_policyengine_version=_running_policyengine_version(),
    )


@dataclass(frozen=True)
class NativeRouteDependencies:
    """Runtime collaborators for native read routes."""

    readiness_probe: Callable[[], bool]
    gateway_client_factory: Callable[[], SimulationGatewayProbe]
    metadata_reader_factory: Callable[[], MetadataReader]
    specification_provider: Callable[[], JSONObject]
    v2_metadata_reader_factory: Callable[[], V2MetadataReader] | None = None

    @classmethod
    def defaults(cls) -> "NativeRouteDependencies":
        """Build lazy defaults without importing country models unnecessarily."""
        return cls(
            readiness_probe=_default_readiness_probe,
            gateway_client_factory=_default_gateway_client_factory,
            metadata_reader_factory=_default_metadata_reader_factory,
            specification_provider=_default_specification_provider,
            v2_metadata_reader_factory=_default_v2_metadata_reader_factory,
        )
