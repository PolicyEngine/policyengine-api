"""Regression guards replacing the former direct local-ORM cache tests."""

from datetime import datetime

from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.ai_analyses import (
    AIAnalysisCache,
    CachedAnalysis,
)
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
)
from policyengine_api.services.ai_analysis_service import (
    AI_ANALYSIS_MODEL,
    AIAnalysisService,
)
from policyengine_api.services.reform_impacts_service import ReformImpactsService


def _context():
    return InMemoryCacheBackend(), CacheNamespace("test", "api")


def test_ai_analysis_service_returns_typed_cached_analysis() -> None:
    backend, namespace = _context()
    cache = AIAnalysisCache(backend, namespace)
    cache.set(
        CachedAnalysis(prompt="prompt", analysis="new"),
        model=AI_ANALYSIS_MODEL,
    )

    analysis = AIAnalysisService(cache).get_existing_analysis("prompt")

    assert isinstance(analysis, CachedAnalysis)
    assert analysis.analysis == "new"


def test_reform_impact_service_writes_typed_expiring_cache_entity() -> None:
    backend, namespace = _context()
    impact = ReformImpactsService(
        ReformImpactCache(backend, namespace)
    ).set_reform_impact(
        country_id="us",
        policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        options={"dataset": "default"},
        options_hash="hash",
        status="computing",
        api_version="1",
        reform_impact_json={},
        start_time=datetime(2026, 1, 1),
        execution_id="job",
    )

    assert isinstance(impact, CachedReformImpact)
    assert impact.options_json == {"dataset": "default"}
