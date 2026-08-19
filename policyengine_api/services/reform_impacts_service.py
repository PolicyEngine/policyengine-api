"""Recoverable reform-impact cache service backed by shared Redis."""

import datetime
from typing import Any

from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.runtime_cache.dependencies import get_runtime_cache_context
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    reform_impact_id,
)


class ReformImpactHandoffError(CacheCoordinationError):
    """Raised when an accepted simulation cannot be recorded for polling."""


class ReformImpactsService:
    """Preserve historical lookup contracts over an expiring cache repository."""

    def __init__(self, cache: ReformImpactCache | None = None) -> None:
        if cache is None:
            context = get_runtime_cache_context()
            cache = ReformImpactCache(context.client, context.namespace)
        self._cache = cache

    def get_recent_reform_impacts(
        self,
        max_results: int,
    ) -> list[CachedReformImpact]:
        return self._cache.recent(max_results)

    def get_all_reform_impacts(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        api_version,
    ) -> list[CachedReformImpact]:
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
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        options_hash_prefix,
        api_version,
    ) -> list[CachedReformImpact]:
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
    ) -> None:
        """Best-effort release; an unavailable cache safely falls back to expiry."""

        try:
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
            )
        except CacheCoordinationError:
            pass

    def set_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options: dict[str, Any],
        options_hash,
        status,
        api_version,
        reform_impact_json: dict[str, Any],
        start_time,
        execution_id: str,
    ) -> CachedReformImpact:
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
        )
        if not self._cache.set(impact):
            raise ReformImpactHandoffError(
                "submitted reform-impact execution could not be stored"
            )
        return impact

    def delete_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
    ) -> None:
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
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        message,
        execution_id: str,
    ) -> CachedReformImpact | None:
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
            end_time=self._now(),
        )

    def set_complete_reform_impact(
        self,
        country_id,
        reform_policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        reform_impact_json: dict[str, Any],
        execution_id,
    ) -> CachedReformImpact | None:
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
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
