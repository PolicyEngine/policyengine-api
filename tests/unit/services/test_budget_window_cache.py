from policyengine_api.services.budget_window_cache import BudgetWindowCache


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key):
        self.values.pop(key, None)


def test_build_key_is_stable_for_request_identity():
    cache = BudgetWindowCache(client=FakeRedis())

    first = cache.build_key(
        country_id="us",
        reform_policy_id=123,
        baseline_policy_id=456,
        region="us",
        dataset="enhanced_cps",
        time_period="budget_window:2026:10",
        options_hash="[option=value]",
        api_version="e1cache01",
    )
    second = cache.build_key(
        country_id="us",
        reform_policy_id=123,
        baseline_policy_id=456,
        region="us",
        dataset="enhanced_cps",
        time_period="budget_window:2026:10",
        options_hash="[option=value]",
        api_version="e1cache01",
    )

    assert first == second
    assert first.startswith("budget_window:v1:us:")


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
