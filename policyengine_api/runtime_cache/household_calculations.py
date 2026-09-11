"""Recoverable calculated-household result caching."""

from dataclasses import asdict, dataclass
from typing import Any

from policyengine_api.runtime_cache.core import (
    CacheBackend,
    CacheNamespace,
    RecoverableJSONCache,
)


HOUSEHOLD_CALCULATION_SCHEMA_VERSION = 1
HOUSEHOLD_CALCULATION_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class HouseholdCalculationIdentity:
    country_id: str
    household_id: int
    policy_id: int
    household_hash: str
    policy_hash: str
    country_package_version: str
    policyengine_version: str


@dataclass(frozen=True)
class CachedHouseholdCalculation:
    household: dict[str, Any]
    warnings: tuple[str, ...] = ()


class HouseholdCalculationCache:
    """Cache a calculated household and its response warnings atomically."""

    def __init__(self, client: CacheBackend, namespace: CacheNamespace) -> None:
        self._cache = RecoverableJSONCache(
            client,
            namespace,
            family="household-calculation",
            schema_version=HOUSEHOLD_CALCULATION_SCHEMA_VERSION,
            ttl_seconds=HOUSEHOLD_CALCULATION_TTL_SECONDS,
        )

    def cache_key(self, identity: HouseholdCalculationIdentity) -> str:
        return self._cache.key(asdict(identity))

    def get(
        self,
        identity: HouseholdCalculationIdentity,
    ) -> CachedHouseholdCalculation | None:
        payload = self._cache.get(asdict(identity))
        if not isinstance(payload, dict):
            return None
        household = payload.get("household")
        warnings = payload.get("warnings")
        if not isinstance(household, dict) or not isinstance(warnings, list):
            return None
        if not all(isinstance(warning, str) for warning in warnings):
            return None
        return CachedHouseholdCalculation(
            household=household,
            warnings=tuple(warnings),
        )

    def set(
        self,
        identity: HouseholdCalculationIdentity,
        value: CachedHouseholdCalculation,
    ) -> bool:
        return self._cache.set(asdict(identity), asdict(value))
