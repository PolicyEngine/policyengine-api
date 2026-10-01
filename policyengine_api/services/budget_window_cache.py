"""Shared, namespaced budget-window state and coordination claims."""

from __future__ import annotations

import time
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
BUDGET_WINDOW_CACHE_SCHEMA_VERSION = 3
BUDGET_WINDOW_STARTING_TTL_SECONDS = 300
BUDGET_WINDOW_BATCH_TTL_SECONDS = 86_400
BUDGET_WINDOW_RESULT_TTL_SECONDS = 2_592_000

BudgetWindowStateStatus = Literal["starting", "submitted", "completed", "failed"]
BudgetWindowFailureType = Literal["spm_validation", "execution"]


class BudgetWindowCacheState(BaseModel):
    """One atomic cache document for a budget-window report."""

    model_config = ConfigDict(frozen=True, strict=True)

    _required_fields: ClassVar[dict[BudgetWindowStateStatus, tuple[str, ...]]] = {
        "starting": ("submission_claim_id",),
        "submitted": ("batch_job_id",),
        "completed": ("result",),
        "failed": ("failure_type", "error"),
    }

    status: BudgetWindowStateStatus
    observability_id: str | None = None
    submission_claim_id: str | None = Field(default=None, min_length=1)
    batch_job_id: str | None = Field(default=None, min_length=1)
    result: dict[str, Any] | None = None
    failure_type: BudgetWindowFailureType | None = None
    error: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)

    @model_validator(mode="after")
    def require_fields_for_status(self) -> BudgetWindowCacheState:
        missing = [
            field
            for field in self._required_fields[self.status]
            if getattr(self, field) is None
        ]
        if missing:
            raise ValueError(f"{self.status} state requires: {', '.join(missing)}")
        return self

    @classmethod
    def from_payload(cls, payload: object) -> BudgetWindowCacheState | None:
        try:
            return cls.model_validate(payload)
        except ValidationError:
            return None


class BudgetWindowCache:
    """Atomic report state plus fail-closed expensive-work coordination."""

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
    def _state_key(cache_key: str) -> str:
        return f"{cache_key}:state"

    @staticmethod
    def _encoded_state(state: BudgetWindowCacheState) -> str:
        return encode_envelope(
            BUDGET_WINDOW_CACHE_FAMILY,
            BUDGET_WINDOW_CACHE_SCHEMA_VERSION,
            state.to_payload(),
        )

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

    def get_state(self, cache_key: str) -> BudgetWindowCacheState | None:
        """Read the complete report state or fail closed on cache outage."""

        started_at = time.perf_counter()
        state_key = self._state_key(cache_key)
        try:
            encoded = self.client.get(state_key)
        except Exception as error:
            self._handle_cache_error(
                "read-state",
                event="coordination-failed",
                started_at=started_at,
            )
            raise CacheCoordinationError(
                "budget-window coordination state is unavailable"
            ) from error

        payload = decode_envelope(
            encoded,
            family=BUDGET_WINDOW_CACHE_FAMILY,
            schema_version=BUDGET_WINDOW_CACHE_SCHEMA_VERSION,
        )
        state = BudgetWindowCacheState.from_payload(payload)
        if encoded is not None and state is None:
            self._handle_cache_error(
                "decode-state",
                event="decode-failed",
                started_at=started_at,
            )
            self._clear_invalid_state(state_key, encoded)
            return None

        record_cache_event(
            family=BUDGET_WINDOW_CACHE_FAMILY,
            event="hit" if state is not None else "miss",
            operation="read-state",
            started_at=started_at,
        )
        return state

    def _clear_invalid_state(self, state_key: str, encoded: object) -> None:
        if isinstance(encoded, bytes):
            try:
                encoded = encoded.decode("utf-8")
            except UnicodeDecodeError:
                return
        if not isinstance(encoded, str):
            return
        try:
            self._claims.release(state_key, encoded)
        except CacheCoordinationError:
            return

    def claim_batch_start(
        self,
        cache_key: str,
        claim_token: str,
        observability_id: str | None,
    ) -> bool:
        state = BudgetWindowCacheState(
            status="starting",
            observability_id=observability_id,
            submission_claim_id=claim_token,
        )
        return self._claims.acquire(
            self._state_key(cache_key),
            self._encoded_state(state),
            ttl_seconds=BUDGET_WINDOW_STARTING_TTL_SECONDS,
        )

    def clear_starting_claim(
        self,
        cache_key: str,
        claim_token: str,
        observability_id: str | None,
    ) -> None:
        state = BudgetWindowCacheState(
            status="starting",
            observability_id=observability_id,
            submission_claim_id=claim_token,
        )
        try:
            self._claims.release(
                self._state_key(cache_key),
                self._encoded_state(state),
            )
        except CacheCoordinationError:
            return

    def store_submitted(
        self,
        cache_key: str,
        batch_job_id: str,
        observability_id: str | None,
    ) -> None:
        state = BudgetWindowCacheState(
            status="submitted",
            observability_id=observability_id,
            batch_job_id=batch_job_id,
        )
        started_at = time.perf_counter()
        try:
            stored = self.client.set(
                self._state_key(cache_key),
                self._encoded_state(state),
                ex=BUDGET_WINDOW_BATCH_TTL_SECONDS,
            )
        except Exception as error:
            self._handle_cache_error(
                "write-submitted-state",
                event="coordination-failed",
                started_at=started_at,
            )
            raise CacheCoordinationError(
                "budget-window coordination state is unavailable"
            ) from error
        if not stored:
            self._handle_cache_error(
                "write-submitted-state",
                event="coordination-failed",
                started_at=started_at,
            )
            raise CacheCoordinationError(
                "budget-window submitted state could not be stored"
            )
        record_cache_event(
            family=BUDGET_WINDOW_CACHE_FAMILY,
            event="coordination-write",
            operation="write-submitted-state",
            started_at=started_at,
        )

    def set_completed_result(
        self,
        cache_key: str,
        result: dict[str, Any],
        observability_id: str | None,
    ) -> bool:
        return self._set_recoverable_state(
            cache_key,
            BudgetWindowCacheState(
                status="completed",
                observability_id=observability_id,
                result=result,
            ),
            operation="write-completed-state",
        )

    def set_terminal_error(
        self,
        cache_key: str,
        error: dict[str, str],
        observability_id: str | None,
    ) -> bool:
        return self._set_recoverable_state(
            cache_key,
            BudgetWindowCacheState(
                status="failed",
                observability_id=observability_id,
                failure_type="spm_validation",
                error=error,
            ),
            operation="write-spm-failure-state",
        )

    def set_execution_failure(
        self,
        cache_key: str,
        result: dict[str, Any],
        observability_id: str | None,
    ) -> bool:
        return self._set_recoverable_state(
            cache_key,
            BudgetWindowCacheState(
                status="failed",
                observability_id=observability_id,
                failure_type="execution",
                error=result,
            ),
            operation="write-execution-failure-state",
        )

    def _set_recoverable_state(
        self,
        cache_key: str,
        state: BudgetWindowCacheState,
        *,
        operation: str,
    ) -> bool:
        started_at = time.perf_counter()
        try:
            stored = self.client.set(
                self._state_key(cache_key),
                self._encoded_state(state),
                ex=jittered_ttl(BUDGET_WINDOW_RESULT_TTL_SECONDS),
            )
        except Exception:
            self._handle_cache_error(
                operation,
                event="write-failed",
                started_at=started_at,
            )
            return False
        record_cache_event(
            family=BUDGET_WINDOW_CACHE_FAMILY,
            event="write",
            operation=operation,
            started_at=started_at,
        )
        return bool(stored)
