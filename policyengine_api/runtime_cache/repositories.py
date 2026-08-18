"""Typed repositories for recoverable API runtime state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import re
import time
from typing import Any

from policyengine_api.runtime_cache.claims import ExpiringClaimStore
from policyengine_api.runtime_cache.core import (
    CacheBackend,
    CacheNamespace,
    RecoverableJSONCache,
    decode_envelope,
    encode_envelope,
    jittered_ttl,
    record_cache_event,
)


HOUSEHOLD_TRACE_SCHEMA_VERSION = 1
HOUSEHOLD_TRACE_TTL_SECONDS = 86_400
AI_ANALYSIS_SCHEMA_VERSION = 1
AI_ANALYSIS_TTL_SECONDS = 604_800
REFORM_IMPACT_SCHEMA_VERSION = 1
REFORM_IMPACT_TTL_SECONDS = 2_592_000
REFORM_IMPACT_INDEX_LIMIT = 1_000
REFORM_IMPACT_START_CLAIM_TTL_SECONDS = 300


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


@dataclass(frozen=True)
class CachedAnalysis:
    prompt: str
    analysis: str
    status: str = "ok"


class AIAnalysisCache:
    def __init__(self, client: CacheBackend, namespace: CacheNamespace) -> None:
        self._cache = RecoverableJSONCache(
            client,
            namespace,
            family="ai-analysis",
            schema_version=AI_ANALYSIS_SCHEMA_VERSION,
            ttl_seconds=AI_ANALYSIS_TTL_SECONDS,
        )

    @staticmethod
    def _inputs(prompt: str, model: str) -> dict[str, str]:
        return {"model": model, "prompt": prompt}

    def get(self, prompt: str, *, model: str) -> CachedAnalysis | None:
        payload = self._cache.get(self._inputs(prompt, model))
        if not isinstance(payload, dict):
            return None
        if payload.get("prompt") != prompt or not isinstance(
            payload.get("analysis"), str
        ):
            return None
        return CachedAnalysis(
            prompt=prompt,
            analysis=payload["analysis"],
            status=str(payload.get("status", "ok")),
        )

    def set(self, value: CachedAnalysis, *, model: str) -> bool:
        return self._cache.set(self._inputs(value.prompt, model), asdict(value))


@dataclass(frozen=True)
class CachedReformImpact:
    reform_impact_id: int
    baseline_policy_id: int
    reform_policy_id: int
    country_id: str
    region: str
    dataset: str
    time_period: str
    options_json: dict[str, Any] | None
    options_hash: str | None
    api_version: str
    reform_impact_json: dict[str, Any]
    status: str
    message: str | None
    start_time: datetime | None
    end_time: datetime | None
    execution_id: str


def _datetime_to_wire(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _datetime_from_wire(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid cached datetime")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _impact_to_wire(impact: CachedReformImpact) -> dict[str, Any]:
    values = asdict(impact)
    values["start_time"] = _datetime_to_wire(impact.start_time)
    values["end_time"] = _datetime_to_wire(impact.end_time)
    return values


def _impact_from_wire(payload: Any) -> CachedReformImpact | None:
    if not isinstance(payload, dict):
        return None
    try:
        return CachedReformImpact(
            reform_impact_id=int(payload["reform_impact_id"]),
            baseline_policy_id=int(payload["baseline_policy_id"]),
            reform_policy_id=int(payload["reform_policy_id"]),
            country_id=str(payload["country_id"]),
            region=str(payload["region"]),
            dataset=str(payload["dataset"]),
            time_period=str(payload["time_period"]),
            options_json=payload.get("options_json"),
            options_hash=payload.get("options_hash"),
            api_version=str(payload["api_version"]),
            reform_impact_json=payload["reform_impact_json"],
            status=str(payload["status"]),
            message=payload.get("message"),
            start_time=_datetime_from_wire(payload.get("start_time")),
            end_time=_datetime_from_wire(payload.get("end_time")),
            execution_id=str(payload["execution_id"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _like_matches(value: str, pattern: str) -> bool:
    expression: list[str] = ["^"]
    escaped = False
    for character in pattern:
        if escaped:
            expression.append(re.escape(character))
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "%":
            expression.append(".*")
        elif character == "_":
            expression.append(".")
        else:
            expression.append(re.escape(character))
    if escaped:
        expression.append(re.escape("\\"))
    expression.append("$")
    return re.match("".join(expression), value) is not None


class ReformImpactCache:
    """Expiring reform-impact values with bounded expiring lookup indexes."""

    family = "reform-impact"

    def __init__(self, client: CacheBackend, namespace: CacheNamespace) -> None:
        self.client = client
        self.namespace = namespace
        self._start_claims = ExpiringClaimStore(client, family=self.family)

    def _start_claim_key(
        self,
        *,
        country_id: str,
        reform_policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        api_version: str,
        options_hash: str,
        target: str,
    ) -> str:
        return self.namespace.key(
            "reform-impact-start-claim",
            REFORM_IMPACT_SCHEMA_VERSION,
            {
                "api_version": api_version,
                "baseline_policy_id": baseline_policy_id,
                "country_id": country_id,
                "dataset": dataset,
                "options_hash": options_hash,
                "reform_policy_id": reform_policy_id,
                "region": region,
                "target": target,
                "time_period": time_period,
            },
        )

    def claim_start(
        self,
        *,
        country_id: str,
        reform_policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        api_version: str,
        options_hash: str,
        target: str,
        claim_token: str,
    ) -> bool:
        """Atomically claim ownership of one reform-impact submission."""

        return self._start_claims.acquire(
            self._start_claim_key(
                country_id=country_id,
                reform_policy_id=reform_policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                api_version=api_version,
                options_hash=options_hash,
                target=target,
            ),
            claim_token,
            ttl_seconds=REFORM_IMPACT_START_CLAIM_TTL_SECONDS,
        )

    def release_start(
        self,
        *,
        country_id: str,
        reform_policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        api_version: str,
        options_hash: str,
        target: str,
        claim_token: str,
    ) -> bool:
        """Release a start claim only when its ownership token still matches."""

        return self._start_claims.release(
            self._start_claim_key(
                country_id=country_id,
                reform_policy_id=reform_policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                api_version=api_version,
                options_hash=options_hash,
                target=target,
            ),
            claim_token,
        )

    def _record_key(self, execution_id: str) -> str:
        return self.namespace.key(
            self.family,
            REFORM_IMPACT_SCHEMA_VERSION,
            {"execution_id": execution_id},
        )

    def _scope_index(self, impact: CachedReformImpact) -> str:
        return self.namespace.key(
            "reform-impact-index",
            REFORM_IMPACT_SCHEMA_VERSION,
            {
                "api_version": impact.api_version,
                "baseline_policy_id": impact.baseline_policy_id,
                "country_id": impact.country_id,
                "dataset": impact.dataset,
                "reform_policy_id": impact.reform_policy_id,
                "region": impact.region,
                "time_period": impact.time_period,
            },
        )

    def _recent_index(self) -> str:
        return self.namespace.family_key(
            "reform-impact-index",
            REFORM_IMPACT_SCHEMA_VERSION,
            "recent",
        )

    @staticmethod
    def _score(impact: CachedReformImpact) -> float:
        if impact.start_time is None:
            return time.time()
        value = impact.start_time
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    def set(self, impact: CachedReformImpact) -> bool:
        record_key = self._record_key(impact.execution_id)
        indexes = (self._scope_index(impact), self._recent_index())
        try:
            ttl_seconds = jittered_ttl(REFORM_IMPACT_TTL_SECONDS)
            with self.client.pipeline(transaction=True) as pipeline:
                pipeline.set(
                    record_key,
                    encode_envelope(
                        self.family,
                        REFORM_IMPACT_SCHEMA_VERSION,
                        _impact_to_wire(impact),
                    ),
                    ex=ttl_seconds,
                )
                for index in indexes:
                    pipeline.zadd(index, {record_key: self._score(impact)})
                    pipeline.zremrangebyrank(
                        index,
                        0,
                        -(REFORM_IMPACT_INDEX_LIMIT + 1),
                    )
                    pipeline.expire(index, ttl_seconds)
                pipeline.execute()
        except Exception:
            record_cache_event(
                family=self.family,
                event="write-failed",
                started_at=time.perf_counter(),
                severity="WARNING",
            )
            return False
        return True

    def get_by_execution_id(self, execution_id: str) -> CachedReformImpact | None:
        try:
            value = self.client.get(self._record_key(execution_id))
        except Exception:
            return None
        return _impact_from_wire(
            decode_envelope(
                value,
                family=self.family,
                schema_version=REFORM_IMPACT_SCHEMA_VERSION,
            )
        )

    def _from_index(self, index: str, limit: int) -> list[CachedReformImpact]:
        try:
            keys = self.client.zrevrange(index, 0, max(limit - 1, 0))  # type: ignore[attr-defined]
            values = [self.client.get(key) for key in keys]
        except Exception:
            return []
        impacts = [
            _impact_from_wire(
                decode_envelope(
                    value,
                    family=self.family,
                    schema_version=REFORM_IMPACT_SCHEMA_VERSION,
                )
            )
            for value in values
        ]
        return [impact for impact in impacts if impact is not None]

    def recent(self, limit: int) -> list[CachedReformImpact]:
        return self._from_index(self._recent_index(), limit)

    def matching(
        self,
        *,
        country_id: str,
        reform_policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        api_version: str,
        options_hash: str,
        options_hash_pattern: str | None = None,
    ) -> list[CachedReformImpact]:
        probe = CachedReformImpact(
            reform_impact_id=0,
            baseline_policy_id=baseline_policy_id,
            reform_policy_id=reform_policy_id,
            country_id=country_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            options_json=None,
            options_hash=options_hash,
            api_version=api_version,
            reform_impact_json={},
            status="",
            message=None,
            start_time=None,
            end_time=None,
            execution_id="",
        )
        impacts = self._from_index(
            self._scope_index(probe),
            REFORM_IMPACT_INDEX_LIMIT,
        )
        selected = [
            impact
            for impact in impacts
            if impact.options_hash == options_hash
            or (
                options_hash_pattern is not None
                and impact.options_hash is not None
                and _like_matches(impact.options_hash, options_hash_pattern)
            )
        ]
        return sorted(
            selected,
            key=lambda impact: (
                impact.options_hash == options_hash,
                impact.start_time or datetime.min,
                impact.reform_impact_id,
            ),
            reverse=True,
        )

    def update(
        self,
        execution_id: str,
        **changes: Any,
    ) -> CachedReformImpact | None:
        impact = self.get_by_execution_id(execution_id)
        if impact is None:
            return None
        updated = replace(impact, **changes)
        return updated if self.set(updated) else None

    def delete_matching_computing(
        self,
        *,
        country_id: str,
        reform_policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
    ) -> None:
        # Deletion historically omits api_version, so search the bounded recent
        # index and remove only matching in-flight values.
        impacts = self.recent(REFORM_IMPACT_INDEX_LIMIT)
        selected = [
            impact
            for impact in impacts
            if impact.country_id == country_id
            and impact.reform_policy_id == reform_policy_id
            and impact.baseline_policy_id == baseline_policy_id
            and impact.region == region
            and impact.dataset == dataset
            and impact.time_period == time_period
            and impact.options_hash == options_hash
            and impact.status == "computing"
        ]
        if not selected:
            return
        try:
            with self.client.pipeline(transaction=True) as pipeline:
                for impact in selected:
                    key = self._record_key(impact.execution_id)
                    pipeline.delete(key)
                    pipeline.zrem(self._scope_index(impact), key)
                    pipeline.zrem(self._recent_index(), key)
                pipeline.execute()
        except Exception:
            return


def reform_impact_id(execution_id: str) -> int:
    """Stable positive cache-local identifier for the historical response field."""

    digest = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:15]
    return int(digest, 16)
