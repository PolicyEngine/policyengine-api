"""AI-analysis cache tests."""

from policyengine_api.runtime_cache.ai_analyses import (
    AIAnalysisCache,
    CachedAnalysis,
)
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend


def test_analysis_cache_is_model_and_prompt_specific_and_expiring() -> None:
    backend = InMemoryCacheBackend()
    cache = AIAnalysisCache(backend, CacheNamespace("test", "api"))
    value = CachedAnalysis(prompt="explain", analysis="answer")

    assert cache.set(value, model="model-a") is True
    assert cache.get("explain", model="model-a") == value
    assert cache.get("explain", model="model-b") is None
    assert cache.get("different", model="model-a") is None
