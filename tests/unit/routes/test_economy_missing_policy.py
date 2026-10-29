"""Economy requests that name a policy their country does not have return 404.

A policy ID belongs to one country, so a US policy requested on a UK economy
route does not exist there. The route answers 404 with the policy ID before the
service takes a submission claim or submits a simulation job, and the shared
cache holds nothing for the request afterwards.
"""

from dataclasses import dataclass
from unittest.mock import Mock

import pytest
from flask import Flask
from flask.testing import FlaskClient

from policyengine_api.libs.simulation_entrypoint import ModalBudgetWindowBatchExecution
from policyengine_api.routes import economy_routes, error_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService

UK_CURRENT_LAW_POLICY_ID = 1
UK_REFORM_POLICY_ID = 7
US_CURRENT_LAW_POLICY_ID = 2
US_REFORM_POLICY_ID = 98557
UK_REFORM_POLICY_JSON = {
    "gov.hmrc.income_tax.rates.uk[0].rate": {"2026-01-01.2100-12-31": 0.21}
}
# Each policy is stored under one country, as in the policy table.
STORED_POLICY_JSON = {
    ("uk", UK_CURRENT_LAW_POLICY_ID): {},
    ("uk", UK_REFORM_POLICY_ID): UK_REFORM_POLICY_JSON,
    ("us", US_CURRENT_LAW_POLICY_ID): {},
    ("us", US_REFORM_POLICY_ID): {
        "gov.irs.credits.ctc.amount.base[0].amount": {"2026-01-01.2100-12-31": 3000}
    },
}
ANNUAL_ROUTE = "annual"
BUDGET_WINDOW_ROUTE = "budget-window"
ROUTE_QUERIES = {
    ANNUAL_ROUTE: ("", [("region", "uk"), ("time_period", "2026")]),
    BUDGET_WINDOW_ROUTE: (
        "/budget-window",
        [("region", "uk"), ("start_year", "2026"), ("window_size", "2")],
    ),
}


def stored_policy_json(country_id: str, policy_id: int) -> dict | None:
    """Return the policy's JSON, or None when the country has no such policy."""
    return STORED_POLICY_JSON.get((country_id, policy_id))


@dataclass(frozen=True)
class EconomyHarness:
    """A Flask client over a real economy service, with its fakes and spies."""

    client: FlaskClient
    route: str
    gateway: Mock
    cache_backend: InMemoryCacheBackend
    annual_claim: Mock
    budget_window_claim: Mock

    def get(self, reform_policy_id: int, baseline_policy_id: int):
        """Request this route's economy impact for the two policy IDs."""
        path_suffix, query = ROUTE_QUERIES[self.route]
        return self.client.get(
            f"/uk/economy/{reform_policy_id}/over/{baseline_policy_id}{path_suffix}",
            query_string=query,
        )

    def submitted_payloads(self) -> list[dict]:
        """Return every simulation payload this route sent to the gateway."""
        submit = (
            self.gateway.run
            if self.route == ANNUAL_ROUTE
            else self.gateway.run_budget_window_batch
        )
        return [call.args[0] for call in submit.call_args_list]

    def stored_cache_keys(self) -> set[str]:
        """Return every key the shared cache holds, claims and records alike."""
        return set(self.cache_backend._values) | set(self.cache_backend._sorted_sets)


@pytest.fixture(params=[ANNUAL_ROUTE, BUDGET_WINDOW_ROUTE])
def economy_harness(request, monkeypatch) -> EconomyHarness:
    """Serve the economy routes from a real service over in-memory caches.

    The policy lookup answers like the policy table, the simulation gateway is
    a mock, and the app-wide error handlers turn an unhandled exception into
    the 500 a deployed request gets.
    """
    namespace = CacheNamespace("test", "economy-missing-policy")
    cache_backend = InMemoryCacheBackend()
    gateway = Mock()
    gateway.resolve_app_name.side_effect = (
        lambda _country_id, version=None, policyengine_version=None: (
            "policyengine-simulation-test",
            version,
        )
    )
    gateway.get_execution_id.return_value = "submitted-job"
    gateway.run_budget_window_batch.return_value = ModalBudgetWindowBatchExecution(
        batch_job_id="submitted-batch", status="submitted"
    )
    policies = Mock()
    policies.get_policy_json.side_effect = stored_policy_json
    reform_impacts = ReformImpactsService(ReformImpactCache(cache_backend, namespace))
    budget_window_cache = BudgetWindowCache(cache_backend, namespace)
    annual_claim = Mock(wraps=reform_impacts.claim_reform_impact_start)
    budget_window_claim = Mock(wraps=budget_window_cache.claim_batch_start)
    monkeypatch.setattr(reform_impacts, "claim_reform_impact_start", annual_claim)
    monkeypatch.setattr(budget_window_cache, "claim_batch_start", budget_window_claim)
    service = EconomyService(
        policy_service_=policies,
        reform_impacts_service_=reform_impacts,
        budget_window_cache_=budget_window_cache,
        simulation_entrypoint_=gateway,
    )
    monkeypatch.setattr(economy_routes, "economy_service", service)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)
    app.register_blueprint(error_routes.error_bp)
    return EconomyHarness(
        client=app.test_client(),
        route=request.param,
        gateway=gateway,
        cache_backend=cache_backend,
        annual_claim=annual_claim,
        budget_window_claim=budget_window_claim,
    )


@pytest.mark.parametrize(
    ("reform_policy_id", "baseline_policy_id", "message"),
    [
        (US_REFORM_POLICY_ID, UK_CURRENT_LAW_POLICY_ID, "Policy #98557 not found."),
        (UK_REFORM_POLICY_ID, US_CURRENT_LAW_POLICY_ID, "Policy #2 not found."),
        (
            US_REFORM_POLICY_ID,
            US_CURRENT_LAW_POLICY_ID,
            "Policies #98557 and #2 not found.",
        ),
        (US_REFORM_POLICY_ID, US_REFORM_POLICY_ID, "Policy #98557 not found."),
    ],
    ids=["reform", "baseline", "both", "same-policy-twice"],
)
def test_a_policy_missing_from_the_country_returns_404_and_stores_nothing(
    economy_harness, reform_policy_id, baseline_policy_id, message
):
    response = economy_harness.get(reform_policy_id, baseline_policy_id)

    assert response.status_code == 404, response.get_json()
    assert response.get_json() == {
        "status": "error",
        "message": message,
        "result": None,
    }
    assert economy_harness.submitted_payloads() == []
    economy_harness.annual_claim.assert_not_called()
    economy_harness.budget_window_claim.assert_not_called()
    assert economy_harness.stored_cache_keys() == set()


def test_a_repeated_request_for_a_missing_policy_returns_404_each_time(
    economy_harness,
):
    responses = [
        economy_harness.get(US_REFORM_POLICY_ID, UK_CURRENT_LAW_POLICY_ID)
        for _attempt in range(3)
    ]

    assert [response.status_code for response in responses] == [404, 404, 404]
    assert economy_harness.submitted_payloads() == []
    assert economy_harness.stored_cache_keys() == set()


def test_policies_stored_for_the_country_are_submitted_unchanged(economy_harness):
    response = economy_harness.get(UK_REFORM_POLICY_ID, UK_CURRENT_LAW_POLICY_ID)

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "computing"
    [payload] = economy_harness.submitted_payloads()
    assert payload["reform"] == UK_REFORM_POLICY_JSON
    assert payload["baseline"] == {}
