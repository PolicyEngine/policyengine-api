"""Recoverable reform-impact cache service backed by shared Redis."""

import contextlib
import datetime
from dataclasses import dataclass
from typing import Any

from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.runtime_cache.dependencies import get_runtime_cache_context
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    ReformImpactIdentity,
    ReformImpactScope,
    ReformImpactStartClaim,
    reform_impact_id,
)


class ReformImpactHandoffError(CacheCoordinationError):
    """Raised when an accepted simulation cannot be recorded for polling."""


@dataclass(frozen=True)
class ReformImpactExecution:
    """The simulation job behind a cached reform impact.

    ``start_time`` is naive local time, as the historical column held it, and
    ``observability_id`` is the diagnostic identifier of the request that
    submitted the job.
    """

    execution_id: str
    start_time: datetime.datetime | None
    observability_id: str | None = None


class ReformImpactsService:
    """Preserve historical lookup contracts over an expiring cache repository."""

    def __init__(self, cache: ReformImpactCache | None = None) -> None:
        """Use this reform-impact cache, or one on the runtime cache if omitted."""
        if cache is None:
            context = get_runtime_cache_context()
            cache = ReformImpactCache(context.client, context.namespace)
        self._cache = cache

    def get_recent_reform_impacts(
        self,
        max_results: int,
    ) -> list[CachedReformImpact]:
        """Return up to ``max_results`` cached impacts, most recently started first."""
        return self._cache.recent(max_results)

    def get_all_reform_impacts(
        self,
        identity: ReformImpactIdentity,
    ) -> list[CachedReformImpact]:
        """Return cached impacts with exactly this options hash, newest first."""
        return self._cache.matching(identity)

    def get_all_reform_impacts_by_options_hash_prefix(
        self,
        identity: ReformImpactIdentity,
        options_hash_prefix: str,
    ) -> list[CachedReformImpact]:
        """Return cached impacts matching the options hash or the prefix pattern.

        ``options_hash_prefix`` is a SQL ``LIKE`` pattern. Exact hash matches come
        first, then the most recently started.
        """
        return self._cache.matching(
            identity,
            options_hash_pattern=options_hash_prefix,
        )

    def claim_reform_impact_start(
        self,
        *,
        identity: ReformImpactIdentity,
        target: str,
        claim_token: str,
        observability_id: str,
    ) -> bool:
        """Fail closed unless this request atomically owns job submission."""
        return self._cache.claim_start(
            identity,
            target=target,
            claim_token=claim_token,
            observability_id=observability_id,
        )

    def get_reform_impact_start_claim(
        self,
        *,
        identity: ReformImpactIdentity,
        target: str,
    ) -> ReformImpactStartClaim | None:
        """Return the current submission owner and diagnostic identifier."""
        return self._cache.get_start_claim(identity, target=target)

    def release_reform_impact_start(
        self,
        *,
        identity: ReformImpactIdentity,
        target: str,
        claim_token: str,
        observability_id: str,
    ) -> None:
        """Best-effort release; an unavailable cache safely falls back to expiry."""
        with contextlib.suppress(CacheCoordinationError):
            self._cache.release_start(
                identity,
                target=target,
                claim_token=claim_token,
                observability_id=observability_id,
            )

    def set_reform_impact(
        self,
        identity: ReformImpactIdentity,
        execution: ReformImpactExecution,
        *,
        options: dict[str, Any],
        status: str,
        reform_impact_json: dict[str, Any],
    ) -> CachedReformImpact:
        """Cache a newly submitted impact by execution ID so later requests can poll it.

        Raise ReformImpactHandoffError if the write fails, because the accepted job
        could not otherwise be found again.
        """
        scope = identity.scope
        impact = CachedReformImpact(
            reform_impact_id=reform_impact_id(execution.execution_id),
            country_id=scope.country_id,
            reform_policy_id=scope.reform_policy_id,
            baseline_policy_id=scope.baseline_policy_id,
            region=scope.region,
            dataset=scope.dataset,
            time_period=scope.time_period,
            options_json=options,
            options_hash=identity.options_hash,
            status=status,
            api_version=identity.api_version,
            reform_impact_json=reform_impact_json,
            message=None,
            start_time=execution.start_time,
            end_time=None,
            execution_id=execution.execution_id,
            observability_id=execution.observability_id,
        )
        if not self._cache.set(impact):
            msg = "submitted reform-impact execution could not be stored"
            raise ReformImpactHandoffError(msg)
        return impact

    def delete_reform_impact(
        self,
        scope: ReformImpactScope,
        options_hash: str,
    ) -> None:
        """Remove this scope's in-flight (computing) impacts, ignoring cache errors."""
        self._cache.delete_matching_computing(scope, options_hash=options_hash)

    def set_error_reform_impact(
        self,
        execution_id: str,
        *,
        message: str,
        error_code: str | None = None,
        keep_seconds: int | None = None,
    ) -> CachedReformImpact | None:
        """Mark this execution's cached impact as failed.

        An ``error_code`` records a typed, terminal failure and clears the worker
        handle. ``keep_seconds`` keeps the failed record for that long instead of
        the usual 30 days; after it expires, a lookup no longer finds it. Only
        this execution's record changes. Return the updated impact, or None if it
        is missing or the write failed.
        """
        return self._cache.update(
            execution_id,
            status="error",
            message=message,
            error_code=error_code,
            clear_execution_id=error_code is not None,
            record_ttl_seconds=keep_seconds,
            end_time=self._now(),
        )

    def set_complete_reform_impact(
        self,
        execution_id: str,
        *,
        reform_impact_json: dict[str, Any],
    ) -> CachedReformImpact | None:
        """Store the finished result on this execution's cached impact.

        Return the updated impact, or None if it is missing or the write failed.
        """
        return self._cache.update(
            execution_id,
            status="ok",
            message="Completed",
            reform_impact_json=reform_impact_json,
            end_time=self._now(),
        )

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
