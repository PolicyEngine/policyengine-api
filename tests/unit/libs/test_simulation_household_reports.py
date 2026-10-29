"""The household report adapter against the generated simulation client.

The client is generated from the Simulation Entrypoint's OpenAPI document and
is not a dependency until a release contains the household report routes, so
these tests skip when it is not installed or lacks those routes. Requests go
to an in-memory transport that answers as the entrypoint does.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

# A client generated before the household report routes lacks this module.
pytest.importorskip(
    "policyengine_api_simulation_client.api.default.get_household_report"
)

from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.libs.simulation_household_reports import (
    SimulationEntrypointHouseholdReports,
    household_reports_from_environment,
    simulation_entrypoint_household_reports,
)
from policyengine_api.request_context import _asgi_request_id
from policyengine_api.services.v2.household_reports.types import (
    HouseholdCalculationError,
    HouseholdCalculationOutput,
    HouseholdCalculationRecord,
    HouseholdPolicyChoice,
    HouseholdReportRecord,
    HouseholdReportRunRecord,
    HouseholdReportSubmission,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ReportStatus,
    RunTrigger,
    SimulationRecordNotFoundError,
    SimulationRequestRefusedError,
    SimulationServiceUnavailableError,
)

BASE_URL = "https://simulation.example.test"
REPORT_ID = UUID("00000000-0000-4000-8000-000000000201")
HOUSEHOLD_ID = UUID("00000000-0000-4000-8000-000000000202")
BASELINE_SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000203")
REFORM_SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000204")
REPORT_RUN_ID = UUID("00000000-0000-4000-8000-000000000205")
BASELINE_RUN_ID = UUID("00000000-0000-4000-8000-000000000206")
REFORM_RUN_ID = UUID("00000000-0000-4000-8000-000000000207")
CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-000000000208")
REFORM_POLICY_ID = UUID("00000000-0000-4000-8000-000000000209")
CREATED_AT = "2026-10-29T12:00:00Z"
CREATED_AT_VALUE = datetime(2026, 10, 29, 12, tzinfo=UTC)
COMPLETED_AT = "2026-10-29T12:00:09Z"
COMPLETED_AT_VALUE = datetime(2026, 10, 29, 12, 0, 9, tzinfo=UTC)
# Keys deliberately out of alphabetical order: the household function lists
# calculated values in the household's own key order.
CALCULATED_HOUSEHOLD = {
    "people": {"you": {"age": {"2026": 40}, "employment_income": {"2026": 50000}}},
    "households": {"your household": {"members": ["you"]}},
}
SPM_CONFIG = {"geography": "national"}
SPM_PROVENANCE = {"forecast": "2026-certified"}


def _calculation_body(
    run_id: UUID,
    simulation_id: UUID,
    policy_id: UUID | None,
    *,
    status: str = "succeeded",
    **changes,
) -> dict:
    succeeded = status == "succeeded"
    return {
        "calculation_id": str(run_id),
        "simulation_id": str(simulation_id),
        "country": "us",
        "household_id": str(HOUSEHOLD_ID),
        "policy_id": None if policy_id is None else str(policy_id),
        "options": {},
        "catalog_version_id": str(CATALOG_VERSION_ID),
        "year": 2026,
        "attempt": 1,
        "trigger": "initial",
        "status": status,
        "created_at": CREATED_AT,
        "dispatched_at": CREATED_AT if status != "pending" else None,
        "completed_at": COMPLETED_AT if succeeded else None,
        "result": (
            {
                "household": CALCULATED_HOUSEHOLD,
                "warnings": ["employment_income was capped"],
                "spm_config": SPM_CONFIG,
                "spm_provenance": SPM_PROVENANCE,
                "bundle": {"policyengine_version": "6.7.5"},
            }
            if succeeded
            else None
        ),
        "error": None,
        **changes,
    }


def _report_body(**changes) -> dict:
    return {
        "report_id": str(REPORT_ID),
        "country": "us",
        "year": 2026,
        "household_id": str(HOUSEHOLD_ID),
        "baseline_simulation_id": str(BASELINE_SIMULATION_ID),
        "reform_simulation_id": str(REFORM_SIMULATION_ID),
        "report_run_id": str(REPORT_RUN_ID),
        "catalog_version_id": str(CATALOG_VERSION_ID),
        "trigger": "initial",
        "status": "succeeded",
        "baseline": _calculation_body(BASELINE_RUN_ID, BASELINE_SIMULATION_ID, None),
        "reform": _calculation_body(
            REFORM_RUN_ID, REFORM_SIMULATION_ID, REFORM_POLICY_ID
        ),
        **changes,
    }


def _calculation_record(
    run_id: UUID, simulation_id: UUID, policy_id: UUID | None
) -> HouseholdCalculationRecord:
    return HouseholdCalculationRecord(
        id=run_id,
        simulation_id=simulation_id,
        policy_id=policy_id,
        status="succeeded",
        attempt=1,
        trigger="initial",
        error=None,
        result=HouseholdCalculationOutput(
            household=CALCULATED_HOUSEHOLD,
            warnings=("employment_income was capped",),
            spm_config=SPM_CONFIG,
            spm_provenance=SPM_PROVENANCE,
        ),
        dispatched_at=CREATED_AT_VALUE,
        completed_at=COMPLETED_AT_VALUE,
        created_at=CREATED_AT_VALUE,
    )


SUCCEEDED_REPORT = HouseholdReportRecord(
    id=REPORT_ID,
    country_id="us",
    year=2026,
    household_id=HOUSEHOLD_ID,
    baseline_simulation_id=BASELINE_SIMULATION_ID,
    reform_simulation_id=REFORM_SIMULATION_ID,
    status=ReportStatus.SUCCEEDED,
    run=HouseholdReportRunRecord(
        id=REPORT_RUN_ID,
        report_id=REPORT_ID,
        trigger="initial",
        tax_benefit_model_version_id=CATALOG_VERSION_ID,
        policyengine_version=None,
        year=2026,
        status=ReportStatus.SUCCEEDED,
        baseline=_calculation_record(BASELINE_RUN_ID, BASELINE_SIMULATION_ID, None),
        reform=_calculation_record(
            REFORM_RUN_ID, REFORM_SIMULATION_ID, REFORM_POLICY_ID
        ),
    ),
)


class SimulationEntrypointStub:
    """Answer each request with the next queued response and record the request."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def adapter(
        self, auth: httpx.Auth | None = None
    ) -> SimulationEntrypointHouseholdReports:
        return simulation_entrypoint_household_reports(
            BASE_URL, auth=auth, transport=httpx.MockTransport(self)
        )


def _submission(*, reform: HouseholdPolicyChoice | None) -> HouseholdReportSubmission:
    return HouseholdReportSubmission(
        country_id="us",
        policyengine_version="6.7.5",
        household_id=HOUSEHOLD_ID,
        baseline=HouseholdPolicyChoice(),
        reform=reform,
    )


def test_submit_sends_the_household_and_policies_and_reads_the_new_report() -> None:
    entrypoint = SimulationEntrypointStub(httpx.Response(202, json=_report_body()))

    report = entrypoint.adapter().submit_report(
        _submission(reform=HouseholdPolicyChoice(policy_id=REFORM_POLICY_ID))
    )

    (request,) = entrypoint.requests
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/v2/household-reports"
    assert json.loads(request.content) == {
        "country": "us",
        "policyengine_version": "6.7.5",
        "household_id": str(HOUSEHOLD_ID),
        "baseline": {"policy_id": None},
        "reform": {"policy_id": str(REFORM_POLICY_ID)},
        "force": False,
        "trigger": "initial",
    }
    assert report == SUCCEEDED_REPORT


def test_a_baseline_only_report_is_sent_without_a_reform() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(202, json=_report_body(reform_simulation_id=None, reform=None))
    )

    report = entrypoint.adapter().submit_report(_submission(reform=None))

    assert json.loads(entrypoint.requests[0].content)["reform"] is None
    assert report.reform_simulation_id is None
    assert report.run is not None
    assert report.run.reform is None


def test_a_calculated_household_keeps_the_key_order_it_was_sent_in() -> None:
    entrypoint = SimulationEntrypointStub(httpx.Response(200, json=_report_body()))

    report = entrypoint.adapter().get_report(REPORT_ID)

    assert report.run is not None
    calculated = report.run.baseline.result
    assert calculated is not None
    assert list(calculated.household) == ["people", "households"]
    assert list(calculated.household["people"]["you"]) == ["age", "employment_income"]


def test_a_report_before_its_first_run_reads_as_not_run() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(
            200,
            json=_report_body(
                household_id=None,
                report_run_id=None,
                catalog_version_id=None,
                trigger=None,
                status=None,
                baseline=None,
                reform=None,
            ),
        )
    )

    report = entrypoint.adapter().get_report(REPORT_ID)

    assert str(entrypoint.requests[0].url) == (
        f"{BASE_URL}/v2/household-reports/{REPORT_ID}"
    )
    assert report.status is ReportStatus.NOT_RUN
    assert report.run is None
    assert report.household_id is None


@pytest.mark.parametrize(
    ("entrypoint_status", "report_status"),
    [
        ("pending", ReportStatus.PENDING),
        ("dispatching", ReportStatus.PENDING),
        ("running", ReportStatus.RUNNING),
    ],
)
def test_an_unfinished_run_reads_without_results(
    entrypoint_status: str, report_status: ReportStatus
) -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(
            200,
            json=_report_body(
                status=entrypoint_status,
                baseline=_calculation_body(
                    BASELINE_RUN_ID,
                    BASELINE_SIMULATION_ID,
                    None,
                    status=entrypoint_status,
                ),
                reform=_calculation_body(
                    REFORM_RUN_ID,
                    REFORM_SIMULATION_ID,
                    REFORM_POLICY_ID,
                    status=entrypoint_status,
                ),
            ),
        )
    )

    report = entrypoint.adapter().get_report(REPORT_ID)

    assert report.status is report_status
    assert report.run is not None
    assert report.run.status is report_status
    assert report.run.baseline.status == entrypoint_status
    assert report.run.baseline.result is None


def test_a_failed_calculation_reads_with_its_error() -> None:
    failure = {
        "code": "household_calculation_failed",
        "message": "The household could not be calculated.",
        "detail": {"errors": [{"code": "unknown_variable"}]},
    }
    entrypoint = SimulationEntrypointStub(
        httpx.Response(
            200,
            json=_report_body(
                status="failed",
                reform=_calculation_body(
                    REFORM_RUN_ID,
                    REFORM_SIMULATION_ID,
                    REFORM_POLICY_ID,
                    status="failed",
                    error=failure,
                ),
            ),
        )
    )

    report = entrypoint.adapter().get_report(REPORT_ID)

    assert report.status is ReportStatus.FAILED
    assert report.run is not None
    assert report.run.reform is not None
    assert report.run.reform.error == HouseholdCalculationError(
        code="household_calculation_failed",
        message="The household could not be calculated.",
        detail={"errors": [{"code": "unknown_variable"}]},
    )


def test_a_run_sends_its_version_trigger_and_force() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(202, json=_report_body(trigger="manual", status="pending"))
    )

    report = entrypoint.adapter().run_report(
        REPORT_ID,
        policyengine_version="6.8.0",
        trigger=RunTrigger.MANUAL,
        force=True,
    )

    (request,) = entrypoint.requests
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/v2/household-reports/{REPORT_ID}/runs"
    assert json.loads(request.content) == {
        "policyengine_version": "6.8.0",
        "trigger": "manual",
        "force": True,
    }
    assert report.run is not None
    assert report.run.trigger == "manual"


def test_an_unknown_report_is_not_found() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(404, json={"detail": "No such household report."})
    )

    with pytest.raises(SimulationRecordNotFoundError):
        entrypoint.adapter().get_report(REPORT_ID)


def test_a_run_of_an_unknown_report_is_not_found() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(404, json={"detail": "No such household report."})
    )
    adapter = entrypoint.adapter()

    with pytest.raises(SimulationRecordNotFoundError):
        adapter.run_report(
            REPORT_ID,
            policyengine_version="6.7.5",
            trigger=RunTrigger.MANUAL,
            force=False,
        )


def test_a_route_the_entrypoint_does_not_serve_means_it_is_unavailable() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(404, json={"detail": "Not Found"})
    )

    with pytest.raises(SimulationServiceUnavailableError):
        entrypoint.adapter().get_report(REPORT_ID)


def test_a_refusal_of_the_callers_data_carries_the_entrypoint_reason() -> None:
    reason = "The policy changes gov.irs.unknown, which catalog 6.7.5 lacks."
    entrypoint = SimulationEntrypointStub(httpx.Response(422, json={"detail": reason}))

    with pytest.raises(SimulationRequestRefusedError) as raised:
        entrypoint.adapter().submit_report(_submission(reform=None))

    assert str(raised.value) == reason


def test_a_request_validation_refusal_names_each_field() -> None:
    entrypoint = SimulationEntrypointStub(
        httpx.Response(
            422,
            json={
                "detail": [
                    {
                        "loc": ["body", "household_id"],
                        "msg": "Input should be a valid UUID",
                        "type": "uuid_parsing",
                    }
                ]
            },
        )
    )

    with pytest.raises(SimulationRequestRefusedError) as raised:
        entrypoint.adapter().submit_report(_submission(reform=None))

    assert str(raised.value) == "household_id: Input should be a valid UUID"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"detail": "No household 0000 in country us."}),
        httpx.Response(422, json={"detail": {"unexpected": "shape"}}),
        httpx.Response(
            503, json={"detail": "The v2 version manifest could not be read."}
        ),
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(403, json={"detail": "Forbidden"}),
        httpx.Response(202, json={"unexpected": "shape"}),
        httpx.Response(202, text="not json"),
    ],
    ids=[
        "refused",
        "malformed-refusal",
        "unavailable",
        "server-error",
        "forbidden",
        "shape",
        "text",
    ],
)
def test_an_unusable_answer_means_the_entrypoint_is_unavailable(
    response: httpx.Response,
) -> None:
    entrypoint = SimulationEntrypointStub(response)

    with pytest.raises(SimulationServiceUnavailableError):
        entrypoint.adapter().submit_report(_submission(reform=None))


def test_a_network_failure_means_the_entrypoint_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    adapter = simulation_entrypoint_household_reports(
        BASE_URL, auth=None, transport=httpx.MockTransport(refuse)
    )

    with pytest.raises(SimulationServiceUnavailableError):
        adapter.get_report(REPORT_ID)


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

    adapter = household_reports_from_environment()

    assert isinstance(adapter, SimulationEntrypointHouseholdReports)
    assert adapter.base_url == BASE_URL


def test_an_unusable_entrypoint_url_makes_reports_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_gateway_auth(monkeypatch)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", "")

    with pytest.raises(SimulationServiceUnavailableError) as raised:
        household_reports_from_environment()

    assert "SIMULATION_ENTRYPOINT_URL" in str(raised.value)


def test_partial_gateway_auth_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gateway_auth(monkeypatch)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", BASE_URL)
    monkeypatch.setenv("GATEWAY_AUTH_ISSUER", "https://auth.example.test")

    with pytest.raises(SimulationServiceUnavailableError) as raised:
        household_reports_from_environment()

    assert "partially configured" in str(raised.value)


@pytest.mark.parametrize(
    "answer",
    [
        _report_body(status="paused"),
        _report_body(baseline={"calculation_id": str(BASELINE_RUN_ID)}),
        _report_body(
            baseline=_calculation_body(
                BASELINE_RUN_ID, BASELINE_SIMULATION_ID, None, status="paused"
            )
        ),
    ],
    ids=[
        "unknown-report-status",
        "malformed-calculation",
        "unknown-calculation-status",
    ],
)
def test_a_success_answer_that_does_not_parse_means_the_entrypoint_is_unavailable(
    answer: dict,
) -> None:
    """The generated client keeps a nested value it cannot parse as it came."""
    entrypoint = SimulationEntrypointStub(httpx.Response(200, json=answer))

    with pytest.raises(SimulationServiceUnavailableError):
        entrypoint.adapter().get_report(REPORT_ID)
