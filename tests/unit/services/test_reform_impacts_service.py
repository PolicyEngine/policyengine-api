from datetime import datetime
from unittest.mock import MagicMock

import pytest

from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.repositories import ReformImpactCache
from policyengine_api.services.reform_impacts_service import (
    ReformImpactHandoffError,
    ReformImpactsService,
)


@pytest.fixture
def service():
    return ReformImpactsService(
        ReformImpactCache(
            InMemoryCacheBackend(),
            CacheNamespace("test", "api"),
        )
    )


def _create_impact(
    service,
    *,
    execution_id: str,
    options_hash: str,
    day: int,
):
    return service.set_reform_impact(
        country_id="us",
        policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        options={"hash": options_hash},
        options_hash=options_hash,
        status="computing",
        api_version="1",
        reform_impact_json={},
        start_time=datetime(2026, 1, day),
        execution_id=execution_id,
    )


def test_set_reform_impact_fails_closed_when_execution_pointer_is_not_stored():
    cache = MagicMock(spec=ReformImpactCache)
    cache.set.return_value = False
    service = ReformImpactsService(cache)

    with pytest.raises(
        ReformImpactHandoffError,
        match="execution could not be stored",
    ):
        _create_impact(
            service,
            execution_id="submitted-job",
            options_hash="hash",
            day=1,
        )


def test_get_recent_reform_impacts_orders_and_limits_results(service):
    older = _create_impact(
        service,
        execution_id="older-job",
        options_hash="older",
        day=1,
    )
    newer = _create_impact(
        service,
        execution_id="newer-job",
        options_hash="newer",
        day=2,
    )

    assert [
        impact.reform_impact_id for impact in service.get_recent_reform_impacts(1)
    ] == [newer.reform_impact_id]
    assert older.reform_impact_id != newer.reform_impact_id


def test_reform_impact_start_claim_is_exclusive_and_releasable(service):
    arguments = {
        "country_id": "us",
        "policy_id": 2,
        "baseline_policy_id": 1,
        "region": "us",
        "dataset": "default",
        "time_period": "2026",
        "options_hash": "resolved-hash",
        "api_version": "1",
        "target": "general",
    }

    assert service.claim_reform_impact_start(**arguments, claim_token="owner")
    assert not service.claim_reform_impact_start(
        **arguments,
        claim_token="contender",
    )
    service.release_reform_impact_start(**arguments, claim_token="owner")
    assert service.claim_reform_impact_start(
        **arguments,
        claim_token="contender",
    )


def test_reform_impact_service_round_trips_models_and_transitions(service):
    exact = _create_impact(
        service,
        execution_id="exact-job",
        options_hash="hash-exact",
        day=1,
    )
    compatible = _create_impact(
        service,
        execution_id="compatible-job",
        options_hash="hash-compatible",
        day=2,
    )

    exact_results = service.get_all_reform_impacts(
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "hash-exact",
        "1",
    )
    compatible_results = service.get_all_reform_impacts_by_options_hash_prefix(
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "hash-exact",
        "hash-%",
        "1",
    )

    assert [impact.reform_impact_id for impact in exact_results] == [
        exact.reform_impact_id
    ]
    assert [impact.reform_impact_id for impact in compatible_results] == [
        exact.reform_impact_id,
        compatible.reform_impact_id,
    ]
    completed = service.set_complete_reform_impact(
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "hash-exact",
        {"result": 1},
        "exact-job",
    )
    failed = service.set_error_reform_impact(
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "hash-compatible",
        "failed",
        "compatible-job",
    )

    assert completed.status == "ok"
    assert completed.reform_impact_json == {"result": 1}
    assert failed.status == "error"
    assert failed.message == "failed"


def test_reform_impact_service_deletes_only_matching_computing_rows(
    service,
):
    _create_impact(
        service,
        execution_id="delete-job",
        options_hash="delete-hash",
        day=1,
    )
    retained = _create_impact(
        service,
        execution_id="retain-job",
        options_hash="retain-hash",
        day=2,
    )

    service.delete_reform_impact(
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "delete-hash",
    )

    remaining = service.get_recent_reform_impacts(10)
    assert all(impact.execution_id != "delete-job" for impact in remaining)
    assert any(
        impact.reform_impact_id == retained.reform_impact_id for impact in remaining
    )


def test_reform_impact_transitions_return_none_for_missing_execution(service):
    assert (
        service.set_error_reform_impact(
            "us",
            2,
            1,
            "us",
            "default",
            "2026",
            "hash",
            "missing",
            "missing-job",
        )
        is None
    )
