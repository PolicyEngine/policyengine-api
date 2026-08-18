"""Fail-closed atomic ownership claims for expensive shared work."""

from __future__ import annotations

import time

from policyengine_api.runtime_cache.core import (
    CacheBackend,
    CacheCoordinationError,
    record_cache_event,
)


COMPARE_AND_DELETE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
""".strip()


class ExpiringClaimStore:
    def __init__(
        self,
        client: CacheBackend,
        *,
        family: str = "coordination",
    ) -> None:
        self.client = client
        self.family = family

    def acquire(self, key: str, token: str, *, ttl_seconds: int) -> bool:
        if not token or ttl_seconds <= 0:
            raise ValueError("claim token and positive TTL are required")
        started_at = time.perf_counter()
        try:
            acquired = bool(self.client.set(key, token, nx=True, ex=ttl_seconds))
        except Exception as error:
            record_cache_event(
                family=self.family,
                event="coordination-failed",
                operation="claim-acquire",
                started_at=started_at,
                severity="WARNING",
            )
            raise CacheCoordinationError(
                "shared-cache ownership could not be established"
            ) from error
        record_cache_event(
            family=self.family,
            event="claim-acquired" if acquired else "claim-contended",
            operation="claim-acquire",
            started_at=started_at,
        )
        return acquired

    def release(self, key: str, token: str) -> bool:
        started_at = time.perf_counter()
        try:
            released = bool(self.client.eval(COMPARE_AND_DELETE, 1, key, token))
        except Exception as error:
            record_cache_event(
                family=self.family,
                event="coordination-failed",
                operation="claim-release",
                started_at=started_at,
                severity="WARNING",
            )
            raise CacheCoordinationError(
                "shared-cache ownership could not be released safely"
            ) from error
        record_cache_event(
            family=self.family,
            event="claim-released" if released else "claim-release-rejected",
            operation="claim-release",
            started_at=started_at,
        )
        return released
