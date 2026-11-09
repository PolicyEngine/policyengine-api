"""Economy requests for a stored policy that simulations can't read answer 422.

Some policies saved before the Public API checked new policies' period keys
and values hold values no simulation can read: US policy 29093 stores two
amounts as text. Every economy job for such a policy fails while the model
reads its parameters, and the route answered 502, logged at ERROR, and replayed
that failure to later requests (issue #4244).

Before it starts an annual or budget-window job, or replays a stored failure,
the service checks the stored policies for what economy simulations refuse
(``policyengine_api.services.economy_policy_values``): a value that fails the
value check new policies get, or a period key the simulation service can't
parse. When any entry fails, the route answers 422 naming the policy, the
parameters and the periods, nothing is submitted or claimed, and nothing is
logged at ERROR. Policies that pass are answered as before.

The tests serve the routes from a real service over in-memory caches, through
a real observability runtime that keeps every record it writes, so they check
every record a request writes, including its ``request.completed`` record.
"""

import importlib
from dataclasses import dataclass, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from flask.testing import FlaskClient
from policyengine_observability import (
    CustomLogDestination,
    OTelConfig,
    configure,
    instrument_flask,
)

from policyengine_api.libs.simulation_entrypoint import ModalBudgetWindowBatchExecution
from policyengine_api.observability import runtime
from policyengine_api.routes import economy_routes, error_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService

# policyengine_api.observability re-exports the runtime object under the name of
# its submodule, so the submodule whose global get_runtime reads is imported by
# its full name.
runtime_module = importlib.import_module("policyengine_api.observability.runtime")

# Cloud Logging's severities from ERROR up: the records the error report reads.
ERROR_OR_ABOVE = frozenset({"ERROR", "CRITICAL", "ALERT", "EMERGENCY"})

CURRENT_LAW_POLICY_ID = 1
REFORM_POLICY_ID = 7
OTHER_REFORM_POLICY_ID = 8
RATE = "gov.hmrc.income_tax.rates.uk[0].rate"
ALLOWANCE = "gov.hmrc.income_tax.allowances.personal_allowance.amount"
READABLE_REFORM = {RATE: {"2026-01-01.2100-12-31": 0.21}}
# Numbers stored as text, as policy 29093 stores them.
UNREADABLE_REFORM = {
    RATE: {"2026-01-01.2100-12-31": "0.21"},
    ALLOWANCE: {"2026-01-01": 12570, "2027-01-01": "13000"},
}
UNREADABLE_OTHER_REFORM = {RATE: {"2026-13-01": 0.22}}
SCALAR_TEXT_POLICY_ID = 9
# A value without periods, which .py applies from 1 January, stored as text.
SCALAR_TEXT_REFORM = {RATE: "0.21"}
VALUE_REQUIREMENT = (
    'a finite number, a boolean, null, a list, or the string "Infinity" or "-Infinity"'
)
UNREADABLE_REFORM_ERRORS = [
    {
        "type": "policy_value",
        "name": ALLOWANCE,
        "path": f"data.{ALLOWANCE}.2027-01-01",
        "message": (
            f"Value at `data.{ALLOWANCE}.2027-01-01` must be {VALUE_REQUIREMENT}, "
            'but it is "13000".'
        ),
        "policy_id": REFORM_POLICY_ID,
    },
    {
        "type": "policy_value",
        "name": RATE,
        "path": f"data.{RATE}.2026-01-01.2100-12-31",
        "message": (
            f"Value at `data.{RATE}.2026-01-01.2100-12-31` must be "
            f'{VALUE_REQUIREMENT}, but it is "0.21".'
        ),
        "policy_id": REFORM_POLICY_ID,
    },
]
UNREADABLE_OTHER_REFORM_ERRORS = [
    {
        "type": "policy_period",
        "name": RATE,
        "path": f"data.{RATE}.2026-13-01",
        "message": (
            f"Period key `2026-13-01` at `data.{RATE}.2026-13-01` must be a date "
            "(YYYY-MM-DD) or an inclusive date range (YYYY-MM-DD.YYYY-MM-DD) of "
            "real calendar dates whose start is no later than its end."
        ),
        "policy_id": OTHER_REFORM_POLICY_ID,
    },
]


def _refusal_message(policy_id: int, errors: list[dict]) -> str:
    return (
        f"Policy #{policy_id} holds period keys or values that simulations can't "
        "read, so no economic impact can be calculated for it: "
        + " ".join(error["message"] for error in errors)
    )


ANNUAL_ROUTE = "annual"
BUDGET_WINDOW_ROUTE = "budget-window"
ROUTE_QUERIES = {
    ANNUAL_ROUTE: ("", [("region", "uk"), ("time_period", "2026")]),
    BUDGET_WINDOW_ROUTE: (
        "/budget-window",
        [("region", "uk"), ("start_year", "2026"), ("window_size", "2")],
    ),
}
REFUSAL_LOG_MESSAGE = (
    "Refused economic impact request for a stored policy that simulations can't read"
)
SKIPPED_CHECK_LOG_MESSAGE = (
    "Could not check the stored policies before replaying a stored economic "
    "impact failure"
)
WORKER_ERROR = (
    "ParameterParsingError: Value in gov.hmrc.income_tax.rates.uk[0].rate"
    "[2026-01-01] has type <class 'str'>"
)


class CollectedRecords:
    """Keeps every structured record a runtime delivers, in delivery order."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def write(self, record: dict[str, object]) -> None:
        self.records.append(record)

    def at_error_or_above(self) -> list[dict[str, object]]:
        return [
            record for record in self.records if record["severity"] in ERROR_OR_ABOVE
        ]

    def with_message(self, message: str) -> list[dict[str, object]]:
        return [record for record in self.records if record.get("message") == message]


@dataclass
class EconomyHarness:
    """A Flask client over a real economy service, with its fakes and spies."""

    client: FlaskClient
    route: str
    gateway: Mock
    stored_policies: dict[int, dict]
    policy_lookup: Mock
    cache_backend: InMemoryCacheBackend
    annual_claim: Mock
    budget_window_claim: Mock
    collected: CollectedRecords

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

    def report_the_job_failed(self) -> None:
        """Make the gateway report the submitted job as failed when polled."""
        self.gateway.get_execution_by_id.return_value = SimpleNamespace(
            error=WORKER_ERROR
        )
        self.gateway.get_execution_status.return_value = "failed"
        self.gateway.get_budget_window_batch_by_id.return_value = (
            ModalBudgetWindowBatchExecution(
                batch_job_id="submitted-batch",
                status="failed",
                error=WORKER_ERROR,
                failed_years=["2026", "2027"],
            )
        )

    def gateway_polls(self) -> int:
        return (
            self.gateway.get_execution_by_id.call_count
            + self.gateway.get_budget_window_batch_by_id.call_count
        )


@pytest.fixture(params=[ANNUAL_ROUTE, BUDGET_WINDOW_ROUTE])
def economy_harness(request, monkeypatch) -> EconomyHarness:
    """Serve the economy routes from a real service over in-memory caches.

    The policy lookup answers from ``stored_policies``, the UK policy table,
    which a test may change between requests. The simulation gateway is a
    mock, and the app-wide error handlers turn an unhandled exception into the
    500 a deployed request gets. The API's observability runtime is replaced
    by one with its logging settings that keeps every record.
    """
    collected = CollectedRecords()
    observability_runtime = configure(
        replace(
            runtime.config,
            logging=replace(
                runtime.config.logging,
                destinations=(
                    CustomLogDestination(
                        name="collected-records",
                        writer_factory=lambda: collected,
                        delivery="inline",
                    ),
                ),
            ),
            otel=OTelConfig(enabled=False),
        )
    )
    monkeypatch.setattr(runtime_module, "runtime", observability_runtime)
    stored_policies: dict[int, dict] = {
        CURRENT_LAW_POLICY_ID: {},
        REFORM_POLICY_ID: UNREADABLE_REFORM,
        OTHER_REFORM_POLICY_ID: UNREADABLE_OTHER_REFORM,
        SCALAR_TEXT_POLICY_ID: SCALAR_TEXT_REFORM,
    }
    policies = Mock()
    policies.get_policy_json.side_effect = lambda country_id, policy_id: (
        stored_policies.get(policy_id) if country_id == "uk" else None
    )
    namespace = CacheNamespace("test", "economy-unreadable-stored-policy")
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
    # Same order as the API app: instrument Flask, then register handlers.
    instrument_flask(app, observability_runtime)
    app.register_blueprint(economy_routes.economy_bp)
    app.register_blueprint(error_routes.error_bp)
    yield EconomyHarness(
        client=app.test_client(),
        route=request.param,
        gateway=gateway,
        stored_policies=stored_policies,
        policy_lookup=policies,
        cache_backend=cache_backend,
        annual_claim=annual_claim,
        budget_window_claim=budget_window_claim,
        collected=collected,
    )
    observability_runtime.shutdown()


def _assert_refused_without_error_records(harness, response, policy_ids, errors):
    """Check the 422 body and that the request wrote nothing at ERROR or above."""
    assert response.status_code == 422, response.get_json()
    assert response.get_json() == {
        "status": "error",
        "message": " ".join(
            _refusal_message(
                policy_id,
                [error for error in errors if error["policy_id"] == policy_id],
            )
            for policy_id in policy_ids
        ),
        "result": None,
        "errors": errors,
    }
    assert harness.collected.at_error_or_above() == []
    [refusal] = harness.collected.with_message(REFUSAL_LOG_MESSAGE)
    assert refusal["severity"] == "WARNING"
    assert refusal["attributes"]["policy_ids"] == ", ".join(map(str, policy_ids))
    assert refusal["attributes"]["invalid_entries"] == len(errors)


@pytest.mark.parametrize(
    ("reform_policy_id", "baseline_policy_id", "policy_ids", "errors"),
    [
        (
            REFORM_POLICY_ID,
            CURRENT_LAW_POLICY_ID,
            [REFORM_POLICY_ID],
            UNREADABLE_REFORM_ERRORS,
        ),
        (
            CURRENT_LAW_POLICY_ID,
            OTHER_REFORM_POLICY_ID,
            [OTHER_REFORM_POLICY_ID],
            UNREADABLE_OTHER_REFORM_ERRORS,
        ),
        (
            REFORM_POLICY_ID,
            OTHER_REFORM_POLICY_ID,
            [REFORM_POLICY_ID, OTHER_REFORM_POLICY_ID],
            UNREADABLE_REFORM_ERRORS + UNREADABLE_OTHER_REFORM_ERRORS,
        ),
        (
            REFORM_POLICY_ID,
            REFORM_POLICY_ID,
            [REFORM_POLICY_ID],
            UNREADABLE_REFORM_ERRORS,
        ),
    ],
    ids=["reform", "baseline", "both", "same-policy-twice"],
)
def test_an_unreadable_stored_policy_answers_422_and_starts_no_job(
    economy_harness, reform_policy_id, baseline_policy_id, policy_ids, errors
):
    response = economy_harness.get(reform_policy_id, baseline_policy_id)

    _assert_refused_without_error_records(economy_harness, response, policy_ids, errors)
    assert economy_harness.submitted_payloads() == []
    economy_harness.annual_claim.assert_not_called()
    economy_harness.budget_window_claim.assert_not_called()
    assert economy_harness.stored_cache_keys() == set()


def test_a_stored_failure_of_an_unreadable_policy_answers_422_instead_of_replaying(
    economy_harness,
):
    """A job submitted before the check existed failed; later requests get 422.

    The policy reads as valid for the first request only, which stands for a
    job that started before this check was deployed.
    """
    economy_harness.stored_policies[REFORM_POLICY_ID] = READABLE_REFORM
    assert economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID).status_code == (
        200
    )
    economy_harness.report_the_job_failed()
    failed = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)
    assert failed.get_json()["status"] == "error", failed.get_json()
    polls_before = economy_harness.gateway_polls()
    economy_harness.stored_policies[REFORM_POLICY_ID] = UNREADABLE_REFORM
    economy_harness.collected.records.clear()

    response = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)

    _assert_refused_without_error_records(
        economy_harness, response, [REFORM_POLICY_ID], UNREADABLE_REFORM_ERRORS
    )
    assert len(economy_harness.submitted_payloads()) == 1
    assert economy_harness.gateway_polls() == polls_before


def test_readable_stored_policies_are_submitted_unchanged(economy_harness):
    economy_harness.stored_policies[REFORM_POLICY_ID] = READABLE_REFORM

    response = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "computing"
    [payload] = economy_harness.submitted_payloads()
    assert payload["reform"] == READABLE_REFORM
    assert payload["baseline"] == {}
    assert economy_harness.collected.with_message(REFUSAL_LOG_MESSAGE) == []


def test_a_stored_failure_of_a_readable_policy_is_replayed_as_before(
    economy_harness,
):
    economy_harness.stored_policies[REFORM_POLICY_ID] = READABLE_REFORM
    economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)
    economy_harness.report_the_job_failed()
    failed = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)

    replayed = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)

    expected_status = 502 if economy_harness.route == ANNUAL_ROUTE else 200
    assert failed.status_code == expected_status, failed.get_json()
    assert replayed.status_code == expected_status, replayed.get_json()
    assert replayed.get_json()["status"] == "error"
    assert WORKER_ERROR in replayed.get_json()["message"]
    assert economy_harness.collected.with_message(REFUSAL_LOG_MESSAGE) == []


def test_a_value_without_periods_that_simulations_cannot_read_answers_422(
    economy_harness,
):
    response = economy_harness.get(SCALAR_TEXT_POLICY_ID, CURRENT_LAW_POLICY_ID)

    _assert_refused_without_error_records(
        economy_harness,
        response,
        [SCALAR_TEXT_POLICY_ID],
        [
            {
                "type": "policy_value",
                "name": RATE,
                "path": f"data.{RATE}",
                "message": (
                    f"Value at `data.{RATE}` must be {VALUE_REQUIREMENT}, "
                    'but it is "0.21".'
                ),
                "policy_id": SCALAR_TEXT_POLICY_ID,
            }
        ],
    )
    assert economy_harness.submitted_payloads() == []


@pytest.mark.parametrize(
    "reform",
    [
        {RATE: {"2026-1-1": 0.21}},
        {RATE: {"2026-4-6.2027-4-5": 0.21}},
        {RATE: 0.21},
    ],
    ids=["unpadded-date", "unpadded-date-range", "value-without-periods"],
)
def test_stored_policies_economy_simulations_read_are_submitted_unchanged(
    economy_harness, reform
):
    """New policies may not be saved this way, but economy simulations read them.

    The simulation service parses period keys with ``strptime``, which also
    reads unpadded months and days, and .py applies a value without periods
    from 1 January of the simulated year.
    """
    economy_harness.stored_policies[REFORM_POLICY_ID] = reform

    response = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)

    assert response.status_code == 200, response.get_json()
    [payload] = economy_harness.submitted_payloads()
    assert payload["reform"] == reform
    assert economy_harness.collected.with_message(REFUSAL_LOG_MESSAGE) == []


def test_a_stored_failure_is_replayed_as_before_when_the_policies_cannot_be_read(
    economy_harness,
):
    """The check before a replay must not make the replay fail."""
    economy_harness.stored_policies[REFORM_POLICY_ID] = READABLE_REFORM
    economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)
    economy_harness.report_the_job_failed()
    failed = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)
    message = "policy table unavailable"
    economy_harness.policy_lookup.get_policy_json.side_effect = RuntimeError(message)
    economy_harness.collected.records.clear()

    replayed = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)

    assert replayed.status_code == failed.status_code, replayed.get_json()
    assert replayed.get_json() == failed.get_json()
    [skipped] = economy_harness.collected.with_message(SKIPPED_CHECK_LOG_MESSAGE)
    assert skipped["severity"] == "WARNING"
    assert skipped["attributes"]["error_type"] == "RuntimeError"


@pytest.mark.parametrize(
    "period_key",
    ["2026-01-01.2025-12-31", "2026-01-01.2026-06-30.2026-12-31", "2026"],
    ids=["reversed-range", "three-dates", "year-only"],
)
def test_a_period_key_the_simulation_service_refuses_answers_422(
    economy_harness, period_key
):
    economy_harness.stored_policies[REFORM_POLICY_ID] = {RATE: {period_key: 0.21}}

    response = economy_harness.get(REFORM_POLICY_ID, CURRENT_LAW_POLICY_ID)

    _assert_refused_without_error_records(
        economy_harness,
        response,
        [REFORM_POLICY_ID],
        [
            {
                "type": "policy_period",
                "name": RATE,
                "path": f"data.{RATE}.{period_key}",
                "message": (
                    f"Period key `{period_key}` at `data.{RATE}.{period_key}` "
                    "must be a date (YYYY-MM-DD) or an inclusive date range "
                    "(YYYY-MM-DD.YYYY-MM-DD) of real calendar dates whose start "
                    "is no later than its end."
                ),
                "policy_id": REFORM_POLICY_ID,
            }
        ],
    )
    assert economy_harness.submitted_payloads() == []
