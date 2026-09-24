from unittest.mock import MagicMock

import pytest

from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.services.budget_window_cache import (
    BUDGET_WINDOW_BATCH_TTL_SECONDS,
    BUDGET_WINDOW_STARTING_TTL_SECONDS,
    BudgetWindowCache,
)


class FakeRedis(InMemoryCacheBackend):
    @property
    def values(self):
        return self._values


class RaisingRedis:
    def __init__(self, *, method):
        self.method = method

    def get(self, key):
        if self.method == "get":
            raise RuntimeError("redis unavailable")
        return None

    def set(self, key, value, nx=False, ex=None):
        if self.method == "set":
            raise RuntimeError("redis unavailable")
        return True

    def delete(self, key):
        if self.method == "delete":
            raise RuntimeError("redis unavailable")

    def eval(self, *_args, **_kwargs):
        raise RuntimeError("redis unavailable")


def test_build_key_is_stable_for_request_identity():
    cache = BudgetWindowCache(client=FakeRedis())

    first = cache.build_key(
        country_id="us",
        reform_policy_id=123,
        baseline_policy_id=456,
        region="us",
        dataset="custom_dataset",
        time_period="budget_window:2026:10",
        options_hash="[option=value]",
        api_version="e1cache01",
    )
    second = cache.build_key(
        country_id="us",
        reform_policy_id=123,
        baseline_policy_id=456,
        region="us",
        dataset="custom_dataset",
        time_period="budget_window:2026:10",
        options_hash="[option=value]",
        api_version="e1cache01",
    )

    assert first == second
    assert first.startswith("policyengine:test:api:budget-window:v2:")


def test_claim_batch_start_allows_one_starter_and_preserves_identity():
    cache = BudgetWindowCache(client=FakeRedis())
    cache_key = "budget_window:v2:us:key"

    assert cache.claim_batch_start(cache_key, "claim-1", "obs-1") is True
    assert cache.claim_batch_start(cache_key, "claim-2", "obs-2") is False

    state = cache.get_state(cache_key)
    assert state is not None
    assert state.status == "starting"
    assert state.submission_claim_id == "claim-1"
    assert state.observability_id == "obs-1"


def test_store_submitted_replaces_starting_state():
    cache = BudgetWindowCache(client=FakeRedis())
    cache_key = "budget_window:v2:us:key"
    cache.claim_batch_start(cache_key, "claim-1", "obs-1")

    cache.store_submitted(cache_key, "fc-parent", "obs-1")

    state = cache.get_state(cache_key)
    assert state is not None
    assert state.status == "submitted"
    assert state.batch_job_id == "fc-parent"
    assert state.observability_id == "obs-1"


def test_completed_result_round_trips_with_identity():
    cache = BudgetWindowCache(client=FakeRedis())
    result = {"kind": "budgetWindow", "totals": {"budgetaryImpact": 10}}

    cache.set_completed_result("budget_window:v2:us:key", result, "obs-1")

    state = cache.get_state("budget_window:v2:us:key")
    assert state is not None
    assert state.status == "completed"
    assert state.result == result
    assert state.observability_id == "obs-1"


def test_spm_validation_failure_round_trips_for_only_its_selection(monkeypatch):
    import policyengine_api.services.budget_window_cache as module

    monkeypatch.setattr(module, "jittered_ttl", lambda _ttl: 123)
    backend = FakeRedis()
    cache = BudgetWindowCache(client=backend)
    error = {"code": "SPM_YEAR_UNAVAILABLE", "message": "No forecast for 2036"}
    identity = {
        "country_id": "us",
        "reform_policy_id": 1,
        "baseline_policy_id": 2,
        "region": "us",
        "dataset": "default",
        "time_period": "budget_window:2035:2",
        "api_version": "v1",
    }
    failed_key = cache.build_key(**identity, options_hash="canonical-selection-a")
    other_key = cache.build_key(**identity, options_hash="canonical-selection-b")

    assert cache.set_terminal_error(failed_key, error, "obs-1")

    stored = BudgetWindowCache(client=backend).get_state(failed_key)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.failure_type == "spm_validation"
    assert stored.error == error
    assert stored.observability_id == "obs-1"
    assert cache.get_state(other_key) is None
    assert set(backend._expires.values()) == {123}
    backend.advance(123)
    assert cache.get_state(failed_key) is None


def test_execution_failure_round_trips_with_identity():
    cache = BudgetWindowCache(client=FakeRedis())
    result = {"status": "error", "error": "simulation failed"}

    assert cache.set_execution_failure("budget_window:v2:us:key", result, "obs-1")

    state = cache.get_state("budget_window:v2:us:key")
    assert state is not None
    assert state.status == "failed"
    assert state.failure_type == "execution"
    assert state.error == result
    assert state.observability_id == "obs-1"


def test_recoverable_state_ttl_is_jittered_but_coordination_ttls_are_exact(
    monkeypatch,
):
    import policyengine_api.services.budget_window_cache as module

    monkeypatch.setattr(module, "jittered_ttl", lambda _ttl: 123)
    redis_client = FakeRedis()
    cache = BudgetWindowCache(client=redis_client)
    cache_key = "budget_window:v2:us:key"
    state_key = f"{cache_key}:state"

    assert cache.set_completed_result(cache_key, {"ok": True}, "obs-1")
    assert redis_client._expires[state_key] == 123

    redis_client.delete(state_key)
    assert cache.claim_batch_start(cache_key, "claim-1", "obs-1")
    assert redis_client._expires[state_key] == BUDGET_WINDOW_STARTING_TTL_SECONDS

    cache.store_submitted(cache_key, "batch-1", "obs-1")
    assert redis_client._expires[state_key] == BUDGET_WINDOW_BATCH_TTL_SECONDS


@pytest.mark.parametrize("invalid_value", ["", "{not-json", "123"])
def test_get_state_removes_invalid_payload(invalid_value, monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)
    redis_client = FakeRedis()
    state_key = "budget_window:v2:us:key:state"
    redis_client.values[state_key] = invalid_value
    cache = BudgetWindowCache(client=redis_client)

    assert cache.get_state("budget_window:v2:us:key") is None
    assert state_key not in redis_client.values
    assert any(
        call.kwargs.get("severity") == "WARNING"
        for call in mock_logger.log_struct.call_args_list
    )


def test_get_state_reraises_read_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)
    cache = BudgetWindowCache(client=RaisingRedis(method="get"))

    with pytest.raises(CacheCoordinationError):
        cache.get_state("budget_window:v2:us:key")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_completed_result_write_error_does_not_change_returned_result(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)
    cache = BudgetWindowCache(client=RaisingRedis(method="set"))

    assert not cache.set_completed_result(
        "budget_window:v2:us:key", {"ok": True}, "obs-1"
    )
    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_claim_batch_start_reraises_claim_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)
    cache = BudgetWindowCache(client=RaisingRedis(method="set"))

    with pytest.raises(CacheCoordinationError):
        cache.claim_batch_start("budget_window:v2:us:key", "claim-1", "obs-1")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_store_submitted_reraises_write_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)
    cache = BudgetWindowCache(client=RaisingRedis(method="set"))

    with pytest.raises(CacheCoordinationError):
        cache.store_submitted("budget_window:v2:us:key", "fc-parent", "obs-1")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_clear_starting_claim_deletes_only_matching_document():
    redis_client = FakeRedis()
    cache = BudgetWindowCache(client=redis_client)
    cache_key = "budget_window:v2:us:key"
    state_key = f"{cache_key}:state"
    cache.claim_batch_start(cache_key, "claim-1", "obs-1")

    cache.clear_starting_claim(cache_key, "claim-2", "obs-1")
    assert state_key in redis_client.values

    cache.clear_starting_claim(cache_key, "claim-1", "different-observability-id")
    assert state_key in redis_client.values

    cache.clear_starting_claim(cache_key, "claim-1", "obs-1")
    assert state_key not in redis_client.values


def test_clear_starting_claim_swallows_coordination_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)
    cache = BudgetWindowCache(client=RaisingRedis(method="eval"))

    cache.clear_starting_claim("budget_window:v2:us:key", "claim-1", "obs-1")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"
