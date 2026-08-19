"""Shared, namespaced budget-window result cache and coordination claims."""

import time
from typing import Any

from policyengine_api.runtime_cache.claims import ExpiringClaimStore
from policyengine_api.runtime_cache.core import (
    CacheBackend,
    CacheCoordinationError,
    CacheNamespace,
    decode_envelope,
    encode_envelope,
    jittered_ttl,
    record_cache_event,
)
from policyengine_api.runtime_cache.dependencies import get_runtime_cache_context


BUDGET_WINDOW_CACHE_FAMILY = "budget-window"
BUDGET_WINDOW_CACHE_SCHEMA_VERSION = 1
BUDGET_WINDOW_STARTING_PREFIX = "starting:"
BUDGET_WINDOW_STARTING_TTL_SECONDS = 300
BUDGET_WINDOW_BATCH_TTL_SECONDS = 86_400
BUDGET_WINDOW_RESULT_TTL_SECONDS = 2_592_000


class BudgetWindowCache:
    """Recoverable results plus fail-closed expensive-work coordination."""

    def __init__(
        self,
        client: CacheBackend | None = None,
        namespace: CacheNamespace | None = None,
    ) -> None:
        if client is None or namespace is None:
            context = get_runtime_cache_context()
            client = client or context.client
            namespace = namespace or context.namespace
        self.client = client
        self.namespace = namespace
        self._claims = ExpiringClaimStore(
            client,
            family=BUDGET_WINDOW_CACHE_FAMILY,
        )

    def build_key(
        self,
        *,
        country_id: str,
        reform_policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str | None,
        api_version: str,
    ) -> str:
        return self.namespace.key(
            BUDGET_WINDOW_CACHE_FAMILY,
            BUDGET_WINDOW_CACHE_SCHEMA_VERSION,
            {
                "api_version": api_version,
                "baseline_policy_id": baseline_policy_id,
                "country_id": country_id,
                "dataset": dataset,
                "options_hash": options_hash,
                "reform_policy_id": reform_policy_id,
                "region": region,
                "time_period": time_period,
            },
        )

    @staticmethod
    def _result_key(cache_key: str) -> str:
        return f"{cache_key}:result"

    @staticmethod
    def _batch_key(cache_key: str) -> str:
        return f"{cache_key}:batch-job-id"

    @staticmethod
    def _handle_cache_error(
        operation: str,
        *,
        event: str,
        started_at: float,
    ) -> None:
        record_cache_event(
            family=BUDGET_WINDOW_CACHE_FAMILY,
            event=event,
            operation=operation,
            started_at=started_at,
            severity="WARNING",
        )

    def get_completed_result(self, cache_key: str) -> dict[str, Any] | None:
        started_at = time.perf_counter()
        try:
            payload = self.client.get(self._result_key(cache_key))
        except Exception:
            self._handle_cache_error(
                "read-result",
                event="connection-failed",
                started_at=started_at,
            )
            return None
        result = decode_envelope(
            payload,
            family=BUDGET_WINDOW_CACHE_FAMILY,
            schema_version=BUDGET_WINDOW_CACHE_SCHEMA_VERSION,
        )
        if payload is not None and result is None:
            self._handle_cache_error(
                "decode-result",
                event="decode-failed",
                started_at=started_at,
            )
        else:
            record_cache_event(
                family=BUDGET_WINDOW_CACHE_FAMILY,
                event="hit" if isinstance(result, dict) else "miss",
                operation="read-result",
                started_at=started_at,
            )
        return result if isinstance(result, dict) else None

    def set_completed_result(
        self,
        cache_key: str,
        result: dict[str, Any],
    ) -> bool:
        started_at = time.perf_counter()
        try:
            stored = self.client.set(
                self._result_key(cache_key),
                encode_envelope(
                    BUDGET_WINDOW_CACHE_FAMILY,
                    BUDGET_WINDOW_CACHE_SCHEMA_VERSION,
                    result,
                ),
                ex=jittered_ttl(BUDGET_WINDOW_RESULT_TTL_SECONDS),
            )
        except Exception:
            self._handle_cache_error(
                "write-result",
                event="write-failed",
                started_at=started_at,
            )
            return False
        record_cache_event(
            family=BUDGET_WINDOW_CACHE_FAMILY,
            event="write",
            operation="write-result",
            started_at=started_at,
        )
        return bool(stored)

    def get_batch_job_id(self, cache_key: str) -> str | None:
        started_at = time.perf_counter()
        try:
            value = self.client.get(self._batch_key(cache_key))
        except Exception as error:
            self._handle_cache_error(
                "read-batch-id",
                event="coordination-failed",
                started_at=started_at,
            )
            raise CacheCoordinationError(
                "budget-window coordination state is unavailable"
            ) from error
        if not isinstance(value, str) or not value:
            record_cache_event(
                family=BUDGET_WINDOW_CACHE_FAMILY,
                event="coordination-miss",
                operation="read-batch-id",
                started_at=started_at,
            )
            return None
        if value.startswith(BUDGET_WINDOW_STARTING_PREFIX):
            record_cache_event(
                family=BUDGET_WINDOW_CACHE_FAMILY,
                event="claim-contended",
                operation="read-batch-id",
                started_at=started_at,
            )
            return None
        record_cache_event(
            family=BUDGET_WINDOW_CACHE_FAMILY,
            event="coordination-hit",
            operation="read-batch-id",
            started_at=started_at,
        )
        return value

    def claim_batch_start(self, cache_key: str, claim_token: str) -> bool:
        try:
            return self._claims.acquire(
                self._batch_key(cache_key),
                f"{BUDGET_WINDOW_STARTING_PREFIX}{claim_token}",
                ttl_seconds=BUDGET_WINDOW_STARTING_TTL_SECONDS,
            )
        except CacheCoordinationError:
            raise

    def store_batch_job_id(self, cache_key: str, batch_job_id: str) -> None:
        started_at = time.perf_counter()
        try:
            stored = self.client.set(
                self._batch_key(cache_key),
                batch_job_id,
                ex=BUDGET_WINDOW_BATCH_TTL_SECONDS,
            )
        except Exception as error:
            self._handle_cache_error(
                "write-batch-id",
                event="coordination-failed",
                started_at=started_at,
            )
            raise CacheCoordinationError(
                "budget-window coordination state is unavailable"
            ) from error
        if not stored:
            self._handle_cache_error(
                "write-batch-id",
                event="coordination-failed",
                started_at=started_at,
            )
            raise CacheCoordinationError(
                "budget-window batch identifier could not be stored"
            )
        record_cache_event(
            family=BUDGET_WINDOW_CACHE_FAMILY,
            event="coordination-write",
            operation="write-batch-id",
            started_at=started_at,
        )

    def clear_starting_claim(self, cache_key: str, claim_token: str) -> None:
        try:
            self._claims.release(
                self._batch_key(cache_key),
                f"{BUDGET_WINDOW_STARTING_PREFIX}{claim_token}",
            )
        except CacheCoordinationError:
            return

    def clear_batch_job_id(self, cache_key: str) -> None:
        started_at = time.perf_counter()
        try:
            self.client.delete(self._batch_key(cache_key))
        except Exception:
            self._handle_cache_error(
                "clear-batch-id",
                event="coordination-failed",
                started_at=started_at,
            )
            return
        record_cache_event(
            family=BUDGET_WINDOW_CACHE_FAMILY,
            event="coordination-cleared",
            operation="clear-batch-id",
            started_at=started_at,
        )
