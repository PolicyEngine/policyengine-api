"""Recoverable computed-household and tracer caching."""

from dataclasses import asdict, dataclass
from typing import Any

from policyengine_api.runtime_cache.core import (
    CacheBackend,
    CacheNamespace,
    RecoverableJSONCache,
)


HOUSEHOLD_TRACE_SCHEMA_VERSION = 1
HOUSEHOLD_TRACE_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class HouseholdTraceIdentity:
    country_id: str
    household_id: int
    policy_id: int
    household_hash: str
    policy_hash: str
    country_package_version: str
    policyengine_version: str


@dataclass(frozen=True)
class HouseholdTraceValue:
    household: dict[str, Any]
    tracer_output: list[str]


class HouseholdTraceCache:
    """One atomic value for a computed household and its matching tracer."""

    def __init__(self, client: CacheBackend, namespace: CacheNamespace) -> None:
        self._cache = RecoverableJSONCache(
            client,
            namespace,
            family="household-trace",
            schema_version=HOUSEHOLD_TRACE_SCHEMA_VERSION,
            ttl_seconds=HOUSEHOLD_TRACE_TTL_SECONDS,
        )

    def cache_key(self, identity: HouseholdTraceIdentity) -> str:
        return self._cache.key(asdict(identity))

    def get(self, identity: HouseholdTraceIdentity) -> HouseholdTraceValue | None:
        payload = self._cache.get(asdict(identity))
        if not isinstance(payload, dict):
            return None
        household = payload.get("household")
        tracer_output = payload.get("tracer_output")
        if not isinstance(household, dict) or not isinstance(tracer_output, list):
            return None
        if not all(isinstance(line, str) for line in tracer_output):
            return None
        return HouseholdTraceValue(
            household=household,
            tracer_output=tracer_output,
        )

    def set(
        self,
        identity: HouseholdTraceIdentity,
        value: HouseholdTraceValue,
    ) -> bool:
        return self._cache.set(asdict(identity), asdict(value))
