"""Recoverable calculated-household result caching."""

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import ValidationError

from policyengine_api.runtime_cache.core import (
    CacheBackend,
    CacheNamespace,
    RecoverableJSONCache,
)
from policyengine_api.spm import validate_spm_calculation_provenance


HOUSEHOLD_CALCULATION_SCHEMA_VERSION = 3
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
    spm: dict[str, Any] | None = None


@dataclass(frozen=True)
class CachedHouseholdCalculation:
    household: dict[str, Any]
    warnings: tuple[str, ...] = ()
    spm_config: dict[str, Any] | None = None
    spm_provenance: dict[str, Any] | None = None


class HouseholdCalculationCache:
    """Cache a calculated household, its warnings and its receipts atomically."""

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
        spm_config = payload.get("spm_config")
        spm_provenance = payload.get("spm_provenance")
        if any(
            value is not None and not isinstance(value, dict)
            for value in (spm_config, spm_provenance)
        ):
            return None
        if identity.spm is None:
            if spm_config is not None or spm_provenance is not None:
                return None
        else:
            try:
                calculation = validate_spm_calculation_provenance(
                    spm_config,
                    spm_provenance,
                )
            except (ValidationError, ValueError):
                return None
            if calculation.spm_config.model_dump(mode="json") != identity.spm:
                return None
        return CachedHouseholdCalculation(
            household=household,
            warnings=tuple(warnings),
            spm_config=spm_config,
            spm_provenance=spm_provenance,
        )

    def set(
        self,
        identity: HouseholdCalculationIdentity,
        value: CachedHouseholdCalculation,
    ) -> bool:
        if identity.spm is None:
            if value.spm_config is not None or value.spm_provenance is not None:
                return False
            return self._cache.set(asdict(identity), asdict(value))
        try:
            calculation = validate_spm_calculation_provenance(
                value.spm_config,
                value.spm_provenance,
            )
        except (ValidationError, ValueError):
            return False
        if calculation.spm_config.model_dump(mode="json") != identity.spm:
            return False
        payload = asdict(value)
        payload["spm_config"] = calculation.spm_config.model_dump(mode="json")
        payload["spm_provenance"] = calculation.spm_provenance.model_dump(
            mode="json", by_alias=True
        )
        return self._cache.set(asdict(identity), payload)
