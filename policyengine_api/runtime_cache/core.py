"""Versioned envelopes, deterministic namespaced keys, and cache semantics."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import random
import time
from typing import Any, Callable, Protocol

from policyengine_api.gcp_logging import logger


CACHE_KEY_ROOT = "policyengine"
COMPLETED_RESULT_TTL_JITTER_FRACTION = 0.10


class CacheBackend(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: str, **kwargs: Any) -> Any: ...
    def delete(self, *keys: str) -> Any: ...
    def pipeline(self, transaction: bool = True): ...
    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any: ...


class CacheCoordinationError(RuntimeError):
    """A fail-closed ownership or deduplication failure."""


@dataclass(frozen=True)
class CacheNamespace:
    environment: str
    service: str

    def key(
        self,
        family: str,
        schema_version: int,
        inputs: dict[str, Any],
        *,
        suffix: str | None = None,
    ) -> str:
        encoded = json.dumps(
            inputs,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        key = (
            f"{CACHE_KEY_ROOT}:{self.environment}:{self.service}:"
            f"{family}:v{schema_version}:{digest}"
        )
        return f"{key}:{suffix}" if suffix else key

    def family_key(self, family: str, schema_version: int, name: str) -> str:
        return (
            f"{CACHE_KEY_ROOT}:{self.environment}:{self.service}:"
            f"{family}:v{schema_version}:{name}"
        )


def encode_envelope(
    family: str,
    schema_version: int,
    payload: Any,
) -> str:
    return json.dumps(
        {
            "family": family,
            "payload": payload,
            "schema_version": schema_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def decode_envelope(
    value: str | bytes | None,
    *,
    family: str,
    schema_version: int,
) -> Any | None:
    if value is None:
        return None
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        decoded = json.loads(value)
    except (UnicodeDecodeError, TypeError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    if decoded.get("family") != family:
        return None
    if decoded.get("schema_version") != schema_version:
        return None
    return decoded.get("payload")


def jittered_ttl(
    ttl_seconds: int,
    *,
    jitter_fraction: float = COMPLETED_RESULT_TTL_JITTER_FRACTION,
    choose_reduction: Callable[[int, int], int] = random.randint,
) -> int:
    """Return a subtract-only jittered TTL for recoverable completed results.

    Coordination and claim TTLs are safety bounds and must not use this helper.
    """

    if ttl_seconds <= 0:
        raise ValueError("cache TTL must be positive")
    if not 0 <= jitter_fraction < 1:
        raise ValueError("TTL jitter fraction must be at least 0 and less than 1")
    max_reduction = int(ttl_seconds * jitter_fraction)
    reduction = choose_reduction(0, max_reduction)
    if not 0 <= reduction <= max_reduction:
        raise ValueError("TTL jitter reduction is outside the permitted range")
    return ttl_seconds - reduction


def record_cache_event(
    *,
    family: str,
    event: str,
    started_at: float,
    severity: str = "INFO",
    operation: str | None = None,
) -> None:
    """Emit one metric-ready event without accepting cache keys or values."""

    payload: dict[str, str | int | float] = {
        "message": "Runtime cache operation",
        "metric_name": "runtime_cache_operations",
        "metric_value": 1,
        "cache_family": family,
        "cache_event": event,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }
    if operation is not None:
        payload["cache_operation"] = operation
    logger.log_struct(payload, severity=severity)


class RecoverableJSONCache:
    """Completed-result cache where failures and invalid values are misses."""

    def __init__(
        self,
        client: CacheBackend,
        namespace: CacheNamespace,
        *,
        family: str,
        schema_version: int,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("cache TTL must be positive")
        self.client = client
        self.namespace = namespace
        self.family = family
        self.schema_version = schema_version
        self.ttl_seconds = ttl_seconds

    def key(self, inputs: dict[str, Any]) -> str:
        return self.namespace.key(self.family, self.schema_version, inputs)

    def get(self, inputs: dict[str, Any]) -> Any | None:
        started_at = time.perf_counter()
        try:
            value = self.client.get(self.key(inputs))
        except Exception:
            record_cache_event(
                family=self.family,
                event="connection-failed",
                started_at=started_at,
                severity="WARNING",
            )
            return None
        payload = decode_envelope(
            value,
            family=self.family,
            schema_version=self.schema_version,
        )
        record_cache_event(
            family=self.family,
            event="hit" if payload is not None else "miss",
            started_at=started_at,
        )
        return payload

    def set(self, inputs: dict[str, Any], payload: Any) -> bool:
        started_at = time.perf_counter()
        try:
            result = self.client.set(
                self.key(inputs),
                encode_envelope(self.family, self.schema_version, payload),
                ex=jittered_ttl(self.ttl_seconds),
            )
        except Exception:
            record_cache_event(
                family=self.family,
                event="write-failed",
                started_at=started_at,
                severity="WARNING",
            )
            return False
        record_cache_event(
            family=self.family,
            event="write",
            started_at=started_at,
        )
        return bool(result)
