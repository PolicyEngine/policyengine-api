"""The economy report adapter against the generated simulation client.

The client is generated from the Simulation Entrypoint's OpenAPI document and
is not a dependency until a release contains the economy report routes, so
these tests skip when it is not installed. Requests go to an in-memory
transport that answers as the entrypoint does.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

pytest.importorskip("policyengine_api_simulation_client")

from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.libs.simulation_economy_reports import (
    SimulationEntrypointEconomyReports,
    economy_reports_from_environment,
    simulation_entrypoint_economy_reports,
)
from policyengine_api.request_context import _asgi_request_id
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ComparisonRecord,
    EconomyReportRecord,
    EconomyReportRunRecord,
    EconomyReportSubmission,
    ReportStatus,
    RunError,
    RunTrigger,
    SimulationChoice,
    SimulationRecord,
    SimulationRecordNotFoundError,
    SimulationRequestRefusedError,
    SimulationRunRecord,
    SimulationServiceUnavailableError,
)

BASE_URL = "https://simulation.example.test"
REPORT_ID = UUID("00000000-0000-4000-8000-000000000001")
BASELINE_SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000002")
REFORM_SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000003")
REPORT_RUN_ID = UUID("00000000-0000-4000-8000-000000000004")
BASELINE_RUN_ID = UUID("00000000-0000-4000-8000-000000000005")
REFORM_RUN_ID = UUID("00000000-0000-4000-8000-000000000006")
CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-000000000007")
REFORM_POLICY_ID = UUID("00000000-0000-4000-8000-000000000008")
CREATED_AT = "2026-10-27T12:00:00Z"
CREATED_AT_VALUE = datetime(2026, 10, 27, 12, tzinfo=UTC)
COMPLETED_AT = "2026-10-27T12:05:00Z"
COMPLETED_AT_VALUE = datetime(2026, 10, 27, 12, 5, tzinfo=UTC)
RESULT = json.loads(
    (
        Path(__file__).parents[2]
        / "fixtures"
        / "simulation_entrypoint"
        / "economy_result_us_congressional_district.json"
    ).read_text()
)


def _simulation_body(simulation_id: UUID, policy_id: UUID | None) -> dict:
    return {
        "id": str(simulation_id),
        "kind": "economy",
        "country": "us",
        "policy_id": None if policy_id is None else str(policy_id),
        "dynamic_id": None,
        "region_code": "congressional_district/CA-12",
        "dataset_name": None,
        "legacy_simulation_id": None,
        "created_at": CREATED_AT,
    }


def _simulation_run_body(run_id: UUID, simulation_id: UUID) -> dict:
    return {
        "id": str(run_id),
        "simulation_id": str(simulation_id),
        "status": "succeeded",
        "attempt": 1,
        "trigger": "initial",
        "error": None,
        "dispatched_at": CREATED_AT,
        "completed_at": COMPLETED_AT,
        "created_at": CREATED_AT,
    }


def _report_run_body(**changes) -> dict:
    return {
        "id": str(REPORT_RUN_ID),
        "report_id": str(REPORT_ID),
        "trigger": "initial",
        "catalog_version_id": str(CATALOG_VERSION_ID),
        "policyengine_version": "6.7.5",
        "year": 2026,
        "status": "succeeded",
        "stage": None,
        "error": None,
        "baseline_run": _simulation_run_body(BASELINE_RUN_ID, BASELINE_SIMULATION_ID),
        "reform_run": _simulation_run_body(REFORM_RUN_ID, REFORM_SIMULATION_ID),
        "comparison": {
            "status": "succeeded",
            "error": None,
            "dispatched_at": COMPLETED_AT,
            "completed_at": COMPLETED_AT,
        },
        "created_at": CREATED_AT,
        **changes,
    }


def _report_body(**changes) -> dict:
    return {
        "id": str(REPORT_ID),
        "country": "us",
        "year": 2026,
        "options": {},
        "legacy_report_id": 615,
        "created_at": CREATED_AT,
        "baseline_simulation": _simulation_body(BASELINE_SIMULATION_ID, None),
        "reform_simulation": _simulation_body(REFORM_SIMULATION_ID, REFORM_POLICY_ID),
        "status": "succeeded",
        "run": _report_run_body(),
        "result": RESULT,
        **changes,
    }


def _simulation_record(simulation_id: UUID, policy_id: UUID | None):
    return SimulationRecord(
        id=simulation_id,
        kind="economy",
        country_id="us",
        policy_id=policy_id,
        dynamic_id=None,
        region_code="congressional_district/CA-12",
        dataset_name=None,
        legacy_simulation_id=None,
        created_at=CREATED_AT_VALUE,
    )


def _simulation_run_record(run_id: UUID, simulation_id: UUID):
    return SimulationRunRecord(
        id=run_id,
        simulation_id=simulation_id,
        status="succeeded",
        attempt=1,
        trigger="initial",
        error=None,
        dispatched_at=CREATED_AT_VALUE,
        completed_at=COMPLETED_AT_VALUE,
        created_at=CREATED_AT_VALUE,
    )


SUCCEEDED_RUN = EconomyReportRunRecord(
    id=REPORT_RUN_ID,
    report_id=REPORT_ID,
    trigger="initial",
    tax_benefit_model_version_id=CATALOG_VERSION_ID,
    policyengine_version="6.7.5",
    year=2026,
    status=ReportStatus.SUCCEEDED,
    stage=None,
    error=None,
    baseline_run=_simulation_run_record(BASELINE_RUN_ID, BASELINE_SIMULATION_ID),
    reform_run=_simulation_run_record(REFORM_RUN_ID, REFORM_SIMULATION_ID),
    comparison=ComparisonRecord(
        status="succeeded",
        error=None,
        dispatched_at=COMPLETED_AT_VALUE,
        completed_at=COMPLETED_AT_VALUE,
    ),
    created_at=CREATED_AT_VALUE,
)


class SimulationEntrypointStub:
    """Answer each request with the next queued response and record the request."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        # The auth flow sends one request object again, so its header is
        # recorded as it was when sent.
        self.authorizations: list[str | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.authorizations.append(request.headers.get("Authorization"))
        return self.responses.pop(0)

    def adapter(self, auth: httpx.Auth | None = None):
        return simulation_entrypoint_economy_reports(
            BASE_URL,
            auth=auth,
            transport=httpx.MockTransport(self),
        )


def _submission() -> EconomyReportSubmission:
    return EconomyReportSubmission(
        country_id="us",
        policyengine_version="6.7.5",
        year=2026,
        region_code="congressional_district/CA-12",
        dataset_name=None,
        baseline=SimulationChoice(),
        reform=SimulationChoice(policy_id=REFORM_POLICY_ID),
    )


def test_submit_sends_the_generated_request_and_reads_the_new_report() -> None:
    pending_run = _report_run_body(
        status="pending",
        stage="queued",
        comparison={
            "status": "pending",
            "error": None,
            "dispatched_at": None,
            "completed_at": None,
        },
    )
    entrypoint = SimulationEntrypointStub(
        httpx.Response(
            201,
            json=_report_body(
                status="pending",
                run=pending_run,
                result=None,
                legacy_report_id=None,
            ),
        )
    )

    report = entrypoint.adapter().submit_report(_submission())

    (request,) = entrypoint.requests
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/v2/economy-reports"
    assert json.loads(request.content) == {
        "country": "us",
        "policyengine_version": "6.7.5",
        "year": 2026,
        "region_code": "congressional_district/CA-12",
        "baseline": {"policy_id": None, "dynamic_id": None},
        "reform": {"policy_id": str(REFORM_POLICY_ID), "dynamic_id": None},
    }
    assert report.status is ReportStatus.PENDING
    assert report.result is None
    assert report.legacy_report_id is None
    assert report.run is not None
    assert report.run.stage == "queued"
    assert report.run.comparison.dispatched_at is None


def test_submit_sends_a_named_dataset() -> None:
    entrypoint = SimulationEntrypointStub(httpx.Response(201, json=_report_body()))
    submission = EconomyReportSubmission(
        **{**_submission().__dict__, "dataset_name": "populace_us_2024"}
    )

    entrypoint.adapter().submit_report(submission)

    assert json.loads(entrypoint.requests[0].content)["dataset_name"] == (
        "populace_us_2024"
    )


def test_a_succeeded_report_reads_back_with_its_exact_result() -> None:
    entrypoint = SimulationEntrypointStub(httpx.Response(200, json=_report_body()))

    report = entrypoint.adapter().get_report(REPORT_ID)

    assert str(entrypoint.requests[0].url) == (
        f"{BASE_URL}/v2/economy-reports/{REPORT_ID}"
    )
    assert report == EconomyReportRecord(
        id=REPORT_ID,
        country_id="us",
        year=2026,
        options={},
        legacy_report_id=615,
        created_at=CREATED_AT_VALUE,
        baseline_simulation=_simulation_record(BASELINE_SIMULATION_ID, None),
        reform_simulation=_simulation_record(REFORM_SIMULATION_ID, REFORM_POLICY_ID),
        status=ReportStatus.SUCCEEDED,
        run=SUCCEEDED_RUN,
        result=RESULT,
    )


def test_a_migrated_report_reads_as_not_run_without_a_run() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(200, json=_report_body(status="not_run", run=None, result=None))
    )

    report = entrypoint.adapter().get_report_by_legacy_id(615)

    assert str(entrypoint.requests[0].url) == (
        f"{BASE_URL}/v2/economy-reports/by-legacy-id/615"
    )
    assert report.status is ReportStatus.NOT_RUN
    assert report.run is None
    assert report.result is None


def test_a_run_sends_its_version_trigger_and_force() -> None:
    failed_run = _report_run_body(
        trigger="manual",
        status="failed",
        error={"code": "invalid_input", "message": "parameter gov.x is unknown"},
    )
    entrypoint = SimulationEntrypointStub(httpx.Response(201, json=failed_run))

    run = entrypoint.adapter().run_report(
        REPORT_ID,
        policyengine_version="6.8.0",
        trigger=RunTrigger.MANUAL,
        force=True,
    )

    (request,) = entrypoint.requests
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/v2/economy-reports/{REPORT_ID}/runs"
    assert json.loads(request.content) == {
        "policyengine_version": "6.8.0",
        "trigger": "manual",
        "force": True,
    }
    assert run.status is ReportStatus.FAILED
    assert run.error == RunError(
        code="invalid_input", message="parameter gov.x is unknown"
    )


def test_runs_are_listed_in_the_order_given() -> None:
    newer = _report_run_body(
        id="00000000-0000-4000-8000-000000000009", trigger="system"
    )
    entrypoint = SimulationEntrypointStub(
        httpx.Response(200, json={"runs": [newer, _report_run_body()]})
    )

    runs = entrypoint.adapter().list_report_runs(REPORT_ID)

    assert str(entrypoint.requests[0].url) == (
        f"{BASE_URL}/v2/economy-reports/{REPORT_ID}/runs"
    )
    assert [run.trigger for run in runs] == ["system", "initial"]
    assert runs[1] == SUCCEEDED_RUN


def test_a_simulation_reads_back() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(
            200, json=_simulation_body(REFORM_SIMULATION_ID, REFORM_POLICY_ID)
        )
    )

    simulation = entrypoint.adapter().get_simulation(REFORM_SIMULATION_ID)

    assert str(entrypoint.requests[0].url) == (
        f"{BASE_URL}/v2/simulations/{REFORM_SIMULATION_ID}"
    )
    assert simulation == _simulation_record(REFORM_SIMULATION_ID, REFORM_POLICY_ID)


def test_an_unknown_report_or_simulation_is_not_found() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(404, json={"detail": f"no economy report {REPORT_ID}"}),
        httpx.Response(404, json={"detail": "no simulation"}),
    )
    adapter = entrypoint.adapter()

    with pytest.raises(SimulationRecordNotFoundError):
        adapter.get_report(REPORT_ID)
    with pytest.raises(SimulationRecordNotFoundError):
        adapter.get_simulation(REFORM_SIMULATION_ID)


def test_a_refusal_carries_the_entrypoint_reason() -> None:
    reason = "us has no catalog for PolicyEngine.py 9.9.9"
    entrypoint = SimulationEntrypointStub(httpx.Response(422, json={"detail": reason}))

    with pytest.raises(SimulationRequestRefusedError) as raised:
        entrypoint.adapter().submit_report(_submission())

    assert str(raised.value) == reason


def test_a_request_validation_refusal_names_each_problem() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(
            422,
            json={
                "detail": [
                    {
                        "loc": ["body", "year"],
                        "msg": "Input should be less than or equal to 2200",
                        "type": "less_than_equal",
                    }
                ]
            },
        )
    )

    with pytest.raises(SimulationRequestRefusedError) as raised:
        entrypoint.adapter().submit_report(_submission())

    assert str(raised.value) == "body.year: Input should be less than or equal to 2200"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"detail": "The simulation database is down."}),
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(403, json={"detail": "missing permission"}),
        httpx.Response(401, json={"detail": "invalid token"}),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, text="not json"),
    ],
    ids=["unavailable", "server-error", "forbidden", "unauthorized", "shape", "text"],
)
def test_an_unusable_answer_means_the_entrypoint_is_unavailable(
    response: httpx.Response,
) -> None:
    entrypoint = SimulationEntrypointStub(response)

    with pytest.raises(SimulationServiceUnavailableError):
        entrypoint.adapter().get_report(REPORT_ID)


def test_a_network_failure_means_the_entrypoint_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    adapter = simulation_entrypoint_economy_reports(
        BASE_URL, auth=None, transport=httpx.MockTransport(refuse)
    )

    with pytest.raises(SimulationServiceUnavailableError):
        adapter.list_report_runs(REPORT_ID)


class CountingBearerAuth(httpx.Auth):
    """Send a numbered token, and a new one after a 401, as the gateway auth does."""

    def __init__(self) -> None:
        self.tokens_issued = 0

    def auth_flow(self, request: httpx.Request):
        self.tokens_issued += 1
        request.headers["Authorization"] = f"Bearer token-{self.tokens_issued}"
        response = yield request
        if response.status_code == 401:
            self.tokens_issued += 1
            request.headers["Authorization"] = f"Bearer token-{self.tokens_issued}"
            yield request


def test_an_expired_token_is_replaced_and_the_request_sent_again() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(401, json={"detail": "expired"}),
        httpx.Response(200, json=_report_body()),
    )

    report = entrypoint.adapter(auth=CountingBearerAuth()).get_report(REPORT_ID)

    assert report.id == REPORT_ID
    assert entrypoint.authorizations == ["Bearer token-1", "Bearer token-2"]


class FailingTokenAuth(httpx.Auth):
    """Fail to fetch a token, as the gateway auth does when Auth0 cannot answer."""

    def auth_flow(self, request: httpx.Request):
        message = "Auth0 token fetch failed: HTTP 503"
        raise GatewayAuthError(message)
        yield request  # pragma: no cover - makes this a generator, as httpx expects


def test_a_failed_token_fetch_means_the_entrypoint_is_unavailable() -> None:
    entrypoint = SimulationEntrypointStub(httpx.Response(200, json=_report_body()))

    with pytest.raises(SimulationServiceUnavailableError) as raised:
        entrypoint.adapter(auth=FailingTokenAuth()).get_report(REPORT_ID)

    assert "token" in str(raised.value)
    assert entrypoint.requests == []


def test_requests_carry_the_current_request_id() -> None:
    entrypoint = SimulationEntrypointStub(httpx.Response(200, json=_report_body()))
    token = _asgi_request_id.set("api-request-id")
    try:
        entrypoint.adapter().get_report(REPORT_ID)
    finally:
        _asgi_request_id.reset(token)

    assert entrypoint.requests[0].headers["X-PolicyEngine-Request-Id"] == (
        "api-request-id"
    )


def _clear_gateway_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GATEWAY_AUTH_ISSUER",
        "GATEWAY_AUTH_AUDIENCE",
        "GATEWAY_AUTH_CLIENT_ID",
        "GATEWAY_AUTH_CLIENT_SECRET",
        "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
        "GATEWAY_AUTH_REQUIRED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_the_environment_names_the_entrypoint_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_gateway_auth(monkeypatch)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", f"{BASE_URL}/")
    monkeypatch.setenv("SIM_ENTRYPOINT", "old_gateway_direct")

    adapter = economy_reports_from_environment()

    assert isinstance(adapter, SimulationEntrypointEconomyReports)
    assert adapter.base_url == BASE_URL


@pytest.mark.parametrize(
    "url",
    ["", "simulation.example.test", "https://user:secret@simulation.example.test"],
    ids=["missing", "no-scheme", "credentials"],
)
def test_an_unusable_entrypoint_url_makes_reports_unavailable(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    _clear_gateway_auth(monkeypatch)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", url)

    with pytest.raises(SimulationServiceUnavailableError) as raised:
        economy_reports_from_environment()

    assert "SIMULATION_ENTRYPOINT_URL" in str(raised.value)


def test_required_gateway_auth_must_be_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_gateway_auth(monkeypatch)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", BASE_URL)
    monkeypatch.setenv("GATEWAY_AUTH_REQUIRED", "1")

    with pytest.raises(SimulationServiceUnavailableError) as raised:
        economy_reports_from_environment()

    assert "GATEWAY_AUTH_ISSUER" in str(raised.value)


def test_partial_gateway_auth_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gateway_auth(monkeypatch)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", BASE_URL)
    monkeypatch.setenv("GATEWAY_AUTH_ISSUER", "https://auth.example.test")

    with pytest.raises(SimulationServiceUnavailableError) as raised:
        economy_reports_from_environment()

    assert "partially configured" in str(raised.value)
