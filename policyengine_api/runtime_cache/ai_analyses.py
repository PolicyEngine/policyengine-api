"""Recoverable AI-analysis caching."""

from dataclasses import asdict, dataclass

from policyengine_api.runtime_cache.core import (
    CacheBackend,
    CacheNamespace,
    RecoverableJSONCache,
)


AI_ANALYSIS_SCHEMA_VERSION = 1
AI_ANALYSIS_TTL_SECONDS = 604_800


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
