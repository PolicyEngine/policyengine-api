"""Recoverable reform-impact cache service backed by shared Redis."""

import contextlib
import datetime
from typing import Any

from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.runtime_cache.dependencies import get_runtime_cache_context
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    ReformImpactStartClaim,
    reform_impact_id,
)


class ReformImpactHandoffError(CacheCoordinationError):
    """Raised when an accepted simulation cannot be recorded for polling."""


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
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
        api_version: str,
    ) -> list[CachedReformImpact]:
        """Return cached impacts with exactly this options hash, newest first."""
        return self._cache.matching(
            country_id=country_id,
            reform_policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            api_version=api_version,
            options_hash=options_hash,
        )

    def get_all_reform_impacts_by_options_hash_prefix(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
        options_hash_prefix: str,
        api_version: str,
    ) -> list[CachedReformImpact]:
        """Return cached impacts matching the options hash or the prefix pattern.

        ``options_hash_prefix`` is a SQL ``LIKE`` pattern. Exact hash matches come
        first, then the most recently started.
        """
        return self._cache.matching(
            country_id=country_id,
            reform_policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            api_version=api_version,
            options_hash=options_hash,
            options_hash_pattern=options_hash_prefix,
        )

    def claim_reform_impact_start(
        self,
        *,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
        api_version: str,
        target: str,
        claim_token: str,
        observability_id: str,
    ) -> bool:
        """Fail closed unless this request atomically owns job submission."""
        return self._cache.claim_start(
            country_id=country_id,
            reform_policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            api_version=api_version,
            options_hash=options_hash,
            target=target,
            claim_token=claim_token,
            observability_id=observability_id,
        )

    def get_reform_impact_start_claim(
        self,
        *,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
        api_version: str,
        target: str,
    ) -> ReformImpactStartClaim | None:
        """Return the current submission owner and diagnostic identifier."""
        return self._cache.get_start_claim(
            country_id=country_id,
            reform_policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            api_version=api_version,
            options_hash=options_hash,
            target=target,
        )

    def release_reform_impact_start(
        self,
        *,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
        api_version: str,
        target: str,
        claim_token: str,
        observability_id: str,
    ) -> None:
        """Best-effort release; an unavailable cache safely falls back to expiry."""
        with contextlib.suppress(CacheCoordinationError):
            self._cache.release_start(
                country_id=country_id,
                reform_policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                api_version=api_version,
                options_hash=options_hash,
                target=target,
                claim_token=claim_token,
                observability_id=observability_id,
            )

    def set_reform_impact(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options: dict[str, Any],
        options_hash: str | None,
        status: str,
        api_version: str,
        reform_impact_json: dict[str, Any],
        start_time: datetime.datetime,
        execution_id: str,
        observability_id: str | None = None,
    ) -> CachedReformImpact:
        """Cache a newly submitted impact by execution ID so later requests can poll it.

        Raise ReformImpactHandoffError if the write fails, because the accepted job
        could not otherwise be found again.
        """
        impact = CachedReformImpact(
            reform_impact_id=reform_impact_id(execution_id),
            country_id=country_id,
            reform_policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            options_json=options,
            options_hash=options_hash,
            status=status,
            api_version=api_version,
            reform_impact_json=reform_impact_json,
            message=None,
            start_time=start_time,
            end_time=None,
            execution_id=execution_id,
            observability_id=observability_id,
        )
        if not self._cache.set(impact):
            msg = "submitted reform-impact execution could not be stored"
            raise ReformImpactHandoffError(msg)
        return impact

    def delete_reform_impact(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
    ) -> None:
        """Remove this scope's in-flight (computing) impacts, ignoring cache errors."""
        self._cache.delete_matching_computing(
            country_id=country_id,
            reform_policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            options_hash=options_hash,
        )

    def set_error_reform_impact(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str | None,
        message: str,
        execution_id: str,
        error_code: str | None = None,
    ) -> CachedReformImpact | None:
        """Mark this execution's cached impact as failed.

        Only ``execution_id`` selects the record; the scope arguments are kept for the
        historical signature and ignored. An ``error_code`` records a typed, terminal
        failure and clears the worker handle. Return the updated impact, or None if
        it is missing or the write failed.
        """
        del (
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            options_hash,
        )
        return self._cache.update(
            execution_id,
            status="error",
            message=message,
            error_code=error_code,
            clear_execution_id=error_code is not None,
            end_time=self._now(),
        )

    def set_complete_reform_impact(
        self,
        country_id: str,
        reform_policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str | None,
        reform_impact_json: dict[str, Any],
        execution_id: str,
    ) -> CachedReformImpact | None:
        """Store the finished result on this execution's cached impact.

        Only ``execution_id`` selects the record; the scope arguments are ignored.
        Return the updated impact, or None if it is missing or the write failed.
        """
        del (
            country_id,
            reform_policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            options_hash,
        )
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
