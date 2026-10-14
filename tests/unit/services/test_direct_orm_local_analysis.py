"""Regression guards replacing the former direct local-ORM cache tests."""

from datetime import datetime

from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    ReformImpactIdentity,
    ReformImpactScope,
)
from policyengine_api.services.reform_impacts_service import (
    ReformImpactExecution,
    ReformImpactsService,
)


def _context():
    return InMemoryCacheBackend(), CacheNamespace("test", "api")


def test_reform_impact_service_writes_typed_expiring_cache_entity() -> None:
    backend, namespace = _context()
    impact = ReformImpactsService(
        ReformImpactCache(backend, namespace)
    ).set_reform_impact(
        ReformImpactIdentity(
            scope=ReformImpactScope(
                country_id="us",
                reform_policy_id=2,
                baseline_policy_id=1,
                region="us",
                dataset="default",
                time_period="2026",
            ),
            api_version="1",
            options_hash="hash",
        ),
        ReformImpactExecution(
            execution_id="job",
            start_time=datetime(2026, 1, 1),
        ),
        options={"dataset": "default"},
        status="computing",
        reform_impact_json={},
    )

    assert isinstance(impact, CachedReformImpact)
    assert impact.options_json == {"dataset": "default"}
