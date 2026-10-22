"""Characterization of the shared-cache keys and how request fields reach them.

Old and new deployments share these Redis keys, so each key string is pinned
exactly, along with the stored reform-impact records and claim errors.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from policyengine_api.runtime_cache.core import CacheCoordinationError, CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
    ReformImpactIdentity,
    ReformImpactScope,
    reform_impact_id,
)
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.reform_impacts_service import (
    ReformImpactExecution,
    ReformImpactsService,
)

NAMESPACE = CacheNamespace("test", "api")
OBSERVABILITY_ID = "00000000-0000-4000-8000-000000000001"
CLAIM_TOKEN = "owner"
SCOPE = {
    "country_id": "us",
    "reform_policy_id": 22,
    "baseline_policy_id": 11,
    "region": "state/ca",
    "dataset": "default",
    "time_period": "2026",
}
START_CLAIM_KEY = "policyengine:test:api:reform-impact-start-claim:v3:"
BUDGET_WINDOW_KEY = "policyengine:test:api:budget-window:v4:"


def _cache() -> ReformImpactCache:
    return ReformImpactCache(InMemoryCacheBackend(), NAMESPACE)


def _service() -> ReformImpactsService:
    return ReformImpactsService(_cache())


OPTIONS_HASH = "[region=state/ca&dataset=default]"


def _identity(**changes: object) -> ReformImpactIdentity:
    values = {**SCOPE, "api_version": "v7", "options_hash": OPTIONS_HASH, **changes}
    return ReformImpactIdentity(
        scope=ReformImpactScope(**{field: values[field] for field in SCOPE}),
        api_version=values["api_version"],
        options_hash=values["options_hash"],
    )


def _claim_arguments(*, target: str = "general", **changes: object) -> dict:
    return {"identity": _identity(**changes), "target": target}


def test_start_claim_key_is_stable():
    key = _cache()._start_claim_key(**_claim_arguments())

    assert key == (
        START_CLAIM_KEY
        + "19e29b251efb3cde28069f9da9d733511630bb7af744423e0347a5ce4a960b4b"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"country_id": "uk"},
        {"reform_policy_id": 23},
        {"baseline_policy_id": 12},
        {"region": "us"},
        {"dataset": "other"},
        {"time_period": "2027"},
        {"api_version": "v8"},
        {"options_hash": "[other]"},
        {"target": "cliff"},
    ],
)
def test_every_scope_field_separates_start_claims(changes):
    cache = _cache()

    assert cache._start_claim_key(**_claim_arguments(**changes)) != (
        cache._start_claim_key(**_claim_arguments())
    )


def test_budget_window_key_is_stable():
    cache = BudgetWindowCache(InMemoryCacheBackend(), NAMESPACE)

    key = cache.build_key(
        ReformImpactScope(**SCOPE),
        options_hash=OPTIONS_HASH,
        api_version="v7",
    )

    assert key == (
        BUDGET_WINDOW_KEY
        + "b7bf1813d90cf73b85ed9614c3a88a8f4b6b94569b2fd7d39a2fa929aac6f76a"
    )


def test_record_and_index_keys_are_stable():
    cache = _cache()
    impact = _stored_impact()

    assert cache._record_key("job-1") == (
        "policyengine:test:api:reform-impact:v3:"
        "1bec8b51d89bb67dc68433bf3cee8119e14f3b329f0a489b589e1129524cc0f7"
    )
    assert cache._scope_index(impact) == (
        "policyengine:test:api:reform-impact-index:v3:"
        "3a5bb6a4515c5bfba4138087969e22b67cbdfbbccaf4e2facec408e341da61f1"
    )
    assert cache._recent_index() == (
        "policyengine:test:api:reform-impact-index:v3:recent"
    )


def _stored_impact(**changes: object) -> CachedReformImpact:
    values = {
        "reform_impact_id": reform_impact_id("job-1"),
        "baseline_policy_id": 11,
        "reform_policy_id": 22,
        "country_id": "us",
        "region": "state/ca",
        "dataset": "default",
        "time_period": "2026",
        "options_json": {"region": "state/ca"},
        "options_hash": "[region=state/ca&dataset=default]",
        "api_version": "v7",
        "reform_impact_json": {},
        "status": "computing",
        "message": None,
        "start_time": datetime(2026, 1, 2, 3, 4, 5),
        "end_time": None,
        "execution_id": "job-1",
        "error_code": None,
        "observability_id": OBSERVABILITY_ID,
    }
    values.update(changes)
    return CachedReformImpact(**values)


def test_set_reform_impact_stores_every_field_from_its_arguments():
    service = _service()

    stored = service.set_reform_impact(
        _identity(),
        ReformImpactExecution(
            execution_id="job-1",
            start_time=datetime(2026, 1, 2, 3, 4, 5),
            observability_id=OBSERVABILITY_ID,
        ),
        options={"region": "state/ca"},
        status="computing",
        reform_impact_json={},
    )

    assert stored == _stored_impact()
    assert service._cache.recent(5) == [_stored_impact()]


def test_lookups_select_by_every_scope_field():
    service = _service()
    service._cache.set(_stored_impact())

    exact = service.get_all_reform_impacts(_identity())
    by_prefix = service.get_all_reform_impacts_by_options_hash_prefix(
        _identity(options_hash="[region=state/ca]"), "[region=state/ca&%"
    )
    swapped_policies = service.get_all_reform_impacts(
        _identity(reform_policy_id=11, baseline_policy_id=22)
    )

    assert exact == [_stored_impact()]
    assert by_prefix == [_stored_impact()]
    assert swapped_policies == []


def test_transitions_update_only_the_execution_record():
    service = _service()
    service._cache.set(_stored_impact())
    service._cache.set(_stored_impact(execution_id="job-2", options_hash="[two]"))

    completed = service.set_complete_reform_impact(
        "job-1", reform_impact_json={"budget": 1}
    )
    failed = service.set_error_reform_impact(
        "job-2",
        message="worker failed",
        error_code="SPM_CONFIGURATION_UNAVAILABLE",
    )

    assert completed == _stored_impact(
        status="ok",
        message="Completed",
        reform_impact_json={"budget": 1},
        end_time=completed.end_time,
    )
    assert completed.end_time is not None
    assert failed == _stored_impact(
        execution_id=None,
        options_hash="[two]",
        status="error",
        message="worker failed",
        error_code="SPM_CONFIGURATION_UNAVAILABLE",
        end_time=failed.end_time,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"country_id": "uk"},
        {"reform_policy_id": 23},
        {"baseline_policy_id": 12},
        {"region": "us"},
        {"dataset": "other"},
        {"time_period": "2027"},
        {"options_hash": "[other]"},
        {"status": "ok"},
    ],
)
def test_delete_keeps_records_differing_in_any_field(changes):
    service = _service()
    service._cache.set(_stored_impact(**changes))

    service.delete_reform_impact(ReformImpactScope(**SCOPE), OPTIONS_HASH)

    assert len(service._cache.recent(5)) == 1


def test_delete_ignores_the_api_version():
    service = _service()
    service._cache.set(_stored_impact(api_version="v0"))

    service.delete_reform_impact(ReformImpactScope(**SCOPE), OPTIONS_HASH)

    assert service._cache.recent(5) == []


def test_delete_swallows_a_failed_cache_write():
    backend = MagicMock(wraps=InMemoryCacheBackend())
    cache = ReformImpactCache(backend, NAMESPACE)
    cache.set(_stored_impact())
    backend.pipeline.side_effect = RuntimeError("redis unavailable")

    ReformImpactsService(cache).delete_reform_impact(
        ReformImpactScope(**SCOPE), OPTIONS_HASH
    )


@pytest.mark.parametrize(
    ("claim_token", "observability_id"),
    [("", OBSERVABILITY_ID), (CLAIM_TOKEN, "not-an-identifier")],
)
def test_claims_require_a_token_and_valid_identifier(claim_token, observability_id):
    cache = _cache()
    message = "a claim token and valid observability identifier are required"

    with pytest.raises(ValueError, match=message):
        cache.claim_start(
            **_claim_arguments(),
            claim_token=claim_token,
            observability_id=observability_id,
        )
    with pytest.raises(ValueError, match=message):
        cache.release_start(
            **_claim_arguments(),
            claim_token=claim_token,
            observability_id=observability_id,
        )


def test_unreachable_claim_store_fails_closed():
    backend = MagicMock()
    backend.get.side_effect = RuntimeError("redis unavailable")
    cache = ReformImpactCache(backend, NAMESPACE)

    with pytest.raises(
        CacheCoordinationError,
        match="reform-impact submission ownership is unavailable",
    ) as caught:
        cache.get_start_claim(**_claim_arguments())

    assert type(caught.value.__cause__) is RuntimeError


def test_service_claim_round_trip_uses_the_same_key():
    service = _service()
    arguments = _claim_arguments()

    assert service.claim_reform_impact_start(
        **arguments, claim_token=CLAIM_TOKEN, observability_id=OBSERVABILITY_ID
    )
    claim = service.get_reform_impact_start_claim(**arguments)
    stored = service._cache.client.get(
        service._cache._start_claim_key(**_claim_arguments())
    )
    service.release_reform_impact_start(
        **arguments, claim_token=CLAIM_TOKEN, observability_id=OBSERVABILITY_ID
    )

    assert claim is not None
    assert claim.submission_claim_id == CLAIM_TOKEN
    assert claim.observability_id == OBSERVABILITY_ID
    assert stored is not None
    assert service.get_reform_impact_start_claim(**arguments) is None
