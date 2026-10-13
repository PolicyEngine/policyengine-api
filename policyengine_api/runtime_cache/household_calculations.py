"""Recoverable calculated-household result caching."""

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import ValidationError

from policyengine_api.runtime_cache.core import (
    CacheBackend,
    CacheNamespace,
    RecoverableJSONCache,
)
from policyengine_api.spm import (
    resolved_spm_configuration,
    validate_spm_calculation_provenance,
)

HOUSEHOLD_CALCULATION_SCHEMA_VERSION = 4
HOUSEHOLD_CALCULATION_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class HouseholdCalculationIdentity:
    """Every input that determines a calculated household; the cache key hashes it.

    The content hashes and package versions make edited inputs and upgraded
    models miss rather than reuse stale results. ``spm`` is the requested
    resolved SPM configuration, or None when the request selected no SPM.
    """

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
    """A calculated household, its warnings, and the SPM receipt if SPM was used."""

    household: dict[str, Any]
    warnings: tuple[str, ...] = ()
    spm_provenance: dict[str, Any] | None = None


class HouseholdCalculationCache:
    """Cache a calculated household, its warnings and its receipts atomically."""

    def __init__(self, client: CacheBackend, namespace: CacheNamespace) -> None:
        """Store results in ``client`` under ``namespace`` for about a day."""
        self._cache = RecoverableJSONCache(
            client,
            namespace,
            family="household-calculation",
            schema_version=HOUSEHOLD_CALCULATION_SCHEMA_VERSION,
            ttl_seconds=HOUSEHOLD_CALCULATION_TTL_SECONDS,
        )

    def cache_key(self, identity: HouseholdCalculationIdentity) -> str:
        """Return the backend key a result for ``identity`` is stored under."""
        return self._cache.key(asdict(identity))

    def get(
        self,
        identity: HouseholdCalculationIdentity,
    ) -> CachedHouseholdCalculation | None:
        """Return the cached result, or None on a miss or any malformed entry.

        An entry whose SPM receipt is missing, invalid, or resolves to a
        different SPM configuration than ``identity`` asks for is also a miss.
        """
        payload = self._cache.get(asdict(identity))
        if not isinstance(payload, dict):
            return None
        household = payload.get("household")
        warnings = payload.get("warnings")
        if not isinstance(household, dict) or not isinstance(warnings, list):
            return None
        if not all(isinstance(warning, str) for warning in warnings):
            return None
        if "spm_config" in payload:
            return None
        spm_provenance = payload.get("spm_provenance")
        if spm_provenance is not None and not isinstance(spm_provenance, dict):
            return None
        if identity.spm is None:
            if spm_provenance is not None:
                return None
        else:
            try:
                receipt = validate_spm_calculation_provenance(spm_provenance)
            except (ValidationError, ValueError):
                return None
            if (
                resolved_spm_configuration(receipt).model_dump(mode="json")
                != identity.spm
            ):
                return None
            spm_provenance = receipt.model_dump(mode="json", by_alias=True)
        return CachedHouseholdCalculation(
            household=household,
            warnings=tuple(warnings),
            spm_provenance=spm_provenance,
        )

    def set(
        self,
        identity: HouseholdCalculationIdentity,
        value: CachedHouseholdCalculation,
    ) -> bool:
        """Cache a result, returning False if it was not written.

        Results whose SPM receipt does not match the identity's SPM request are
        refused rather than stored, so a later read cannot serve them.
        """
        if identity.spm is None:
            if value.spm_provenance is not None:
                return False
            return self._cache.set(asdict(identity), asdict(value))
        try:
            receipt = validate_spm_calculation_provenance(value.spm_provenance)
        except (ValidationError, ValueError):
            return False
        if resolved_spm_configuration(receipt).model_dump(mode="json") != identity.spm:
            return False
        payload = asdict(value)
        payload["spm_provenance"] = receipt.model_dump(mode="json", by_alias=True)
        return self._cache.set(asdict(identity), payload)
