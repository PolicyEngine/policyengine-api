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
    assert first.startswith("policyengine:test:api:budget-window:v1:")


def test_claim_batch_start_allows_one_starter():
    cache = BudgetWindowCache(client=FakeRedis())

    assert cache.claim_batch_start("budget_window:v1:us:key", "process-1") is True
    assert cache.claim_batch_start("budget_window:v1:us:key", "process-2") is False
    assert cache.get_batch_job_id("budget_window:v1:us:key") is None


def test_store_batch_job_id_replaces_starting_claim():
    cache = BudgetWindowCache(client=FakeRedis())
    cache.claim_batch_start("budget_window:v1:us:key", "process-1")

    cache.store_batch_job_id("budget_window:v1:us:key", "fc-parent")

    assert cache.get_batch_job_id("budget_window:v1:us:key") == "fc-parent"


def test_completed_result_round_trips():
    cache = BudgetWindowCache(client=FakeRedis())
    result = {"kind": "budgetWindow", "totals": {"budgetaryImpact": 10}}

    cache.set_completed_result("budget_window:v1:us:key", result)

    assert cache.get_completed_result("budget_window:v1:us:key") == result


def test_completed_result_ttl_is_jittered_but_coordination_ttls_are_exact(
    monkeypatch,
):
    import policyengine_api.services.budget_window_cache as module

    monkeypatch.setattr(module, "jittered_ttl", lambda _ttl: 123)
    redis_client = FakeRedis()
    cache = BudgetWindowCache(client=redis_client)
    cache_key = "budget_window:v1:us:key"

    assert cache.set_completed_result(cache_key, {"ok": True})
    assert redis_client._expires[f"{cache_key}:result"] == 123

    assert cache.claim_batch_start(cache_key, "process-1")
    assert (
        redis_client._expires[f"{cache_key}:batch-job-id"]
        == BUDGET_WINDOW_STARTING_TTL_SECONDS
    )

    cache.store_batch_job_id(cache_key, "batch-1")
    assert (
        redis_client._expires[f"{cache_key}:batch-job-id"]
        == BUDGET_WINDOW_BATCH_TTL_SECONDS
    )


def test_get_completed_result_returns_none_for_empty_payload():
    redis_client = FakeRedis()
    redis_client.values["budget_window:v1:us:key:result"] = ""
    cache = BudgetWindowCache(client=redis_client)

    assert cache.get_completed_result("budget_window:v1:us:key") is None


def test_get_completed_result_returns_none_for_invalid_json(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "policyengine_api.runtime_cache.core.logger",
        mock_logger,
    )
    redis_client = FakeRedis()
    redis_client.values["budget_window:v1:us:key:result"] = "{not-json"
    cache = BudgetWindowCache(client=redis_client)

    assert cache.get_completed_result("budget_window:v1:us:key") is None
    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_get_completed_result_treats_read_errors_as_misses(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "policyengine_api.runtime_cache.core.logger",
        mock_logger,
    )
    cache = BudgetWindowCache(client=RaisingRedis(method="get"))

    assert cache.get_completed_result("budget_window:v1:us:key") is None

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_set_completed_result_does_not_invalidate_compute_on_write_error(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "policyengine_api.runtime_cache.core.logger",
        mock_logger,
    )
    cache = BudgetWindowCache(client=RaisingRedis(method="set"))

    assert not cache.set_completed_result("budget_window:v1:us:key", {"ok": True})

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_get_batch_job_id_ignores_empty_non_string_and_starting_values():
    redis_client = FakeRedis()
    cache = BudgetWindowCache(client=redis_client)

    redis_client.values["budget_window:v1:us:key:batch-job-id"] = ""
    assert cache.get_batch_job_id("budget_window:v1:us:key") is None

    redis_client.values["budget_window:v1:us:key:batch-job-id"] = 123
    assert cache.get_batch_job_id("budget_window:v1:us:key") is None

    redis_client.values["budget_window:v1:us:key:batch-job-id"] = "starting:process-1"
    assert cache.get_batch_job_id("budget_window:v1:us:key") is None


def test_get_batch_job_id_reraises_read_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "policyengine_api.runtime_cache.core.logger",
        mock_logger,
    )
    cache = BudgetWindowCache(client=RaisingRedis(method="get"))

    with pytest.raises(CacheCoordinationError):
        cache.get_batch_job_id("budget_window:v1:us:key")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_claim_batch_start_reraises_claim_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "policyengine_api.runtime_cache.core.logger",
        mock_logger,
    )
    cache = BudgetWindowCache(client=RaisingRedis(method="set"))

    with pytest.raises(CacheCoordinationError):
        cache.claim_batch_start("budget_window:v1:us:key", "process-1")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_store_batch_job_id_reraises_write_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "policyengine_api.runtime_cache.core.logger",
        mock_logger,
    )
    cache = BudgetWindowCache(client=RaisingRedis(method="set"))

    with pytest.raises(CacheCoordinationError):
        cache.store_batch_job_id("budget_window:v1:us:key", "fc-parent")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_clear_starting_claim_deletes_only_matching_token():
    redis_client = FakeRedis()
    cache = BudgetWindowCache(client=redis_client)
    cache.claim_batch_start("budget_window:v1:us:key", "process-1")

    cache.clear_starting_claim("budget_window:v1:us:key", "process-2")

    assert (
        redis_client.values["budget_window:v1:us:key:batch-job-id"]
        == "starting:process-1"
    )

    cache.clear_starting_claim("budget_window:v1:us:key", "process-1")

    assert "budget_window:v1:us:key:batch-job-id" not in redis_client.values


def test_clear_starting_claim_logs_and_swallows_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "policyengine_api.runtime_cache.core.logger",
        mock_logger,
    )
    cache = BudgetWindowCache(client=RaisingRedis(method="get"))

    cache.clear_starting_claim("budget_window:v1:us:key", "process-1")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"


def test_clear_batch_job_id_logs_and_swallows_errors(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "policyengine_api.runtime_cache.core.logger",
        mock_logger,
    )
    cache = BudgetWindowCache(client=RaisingRedis(method="delete"))

    cache.clear_batch_job_id("budget_window:v1:us:key")

    assert mock_logger.log_struct.call_args.kwargs["severity"] == "WARNING"
