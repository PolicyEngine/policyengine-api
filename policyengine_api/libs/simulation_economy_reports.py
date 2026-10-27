"""The Simulation Entrypoint's economy report routes, through its generated client.

This is the only module that imports ``policyengine_api_simulation_client``,
the client generated from the Simulation Entrypoint's OpenAPI document.
Everything else uses ``EconomyReportSimulation``, which this module
implements, so the rest of the code and its tests do not need the client.
Nothing imports this module at module level, so the application starts
without the client installed and the economy report routes then answer 503.

The economy report routes exist only on the Cloud Run Simulation Entrypoint,
so requests always go to ``SIMULATION_ENTRYPOINT_URL``, whichever entrypoint
``SIM_ENTRYPOINT`` selects for the v1 routes. They carry the gateway bearer
token, which needs ``simulation:submit`` to submit and ``simulation:read``
to read.

The generated client parses only the success answers the entrypoint's
OpenAPI document describes. Its refusals (404, 422 with a text ``detail``,
503) are read by a response hook before the generated parser sees them.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar

import httpx
from policyengine_api_simulation_client import AuthenticatedClient
from policyengine_api_simulation_client.api.default import (
    get_economy_report,
    get_economy_report_by_legacy_id,
    get_simulation,
    list_economy_report_runs,
    run_economy_report,
    submit_economy_report,
)
from policyengine_api_simulation_client.models import (
    EconomyReportResponse,
    EconomyReportRunRequest,
    EconomyReportRunRequestTrigger,
    EconomyReportRunResponse,
    EconomyReportRunsResponse,
    EconomyReportSubmissionRequest,
    EconomyReportSubmissionRequestCountry,
    SimulationChoiceRequest,
    SimulationResponse,
)
from policyengine_api_simulation_client.types import UNSET
from policyengine_observability import instrument_httpx

from policyengine_api.libs.gateway_auth import (
    GatewayAuthError,
    gateway_bearer_auth_from_environment,
)
from policyengine_api.libs.simulation_http import (
    attach_request_identifiers,
    required_base_url,
)
from policyengine_api.observability import get_runtime
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ComparisonRecord,
    EconomyReportRecord,
    EconomyReportRunRecord,
    ReportStatus,
    RunError,
    SimulationRecord,
    SimulationRecordNotFoundError,
    SimulationRequestRefusedError,
    SimulationRunRecord,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from policyengine_api_simulation_client.models import (
        ComparisonResponse,
        RunErrorResponse,
        SimulationRunResponse,
    )
    from policyengine_api_simulation_client.types import Response

    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportSubmission,
        RunTrigger,
        SimulationChoice,
    )

SIMULATION_ENTRYPOINT_URL_ENV = "SIMULATION_ENTRYPOINT_URL"
REQUEST_TIMEOUT_SECONDS = 30.0
ParsedT = TypeVar("ParsedT")


def _refusal_reason(response: httpx.Response) -> str:
    """Return the ``detail`` of an error answer as text."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.text[:500] or f"HTTP {response.status_code}"
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, list) and detail:
        return "; ".join(
            ".".join(str(part) for part in problem.get("loc", ()))
            + f": {problem.get('msg', '')}"
            if isinstance(problem, dict)
            else str(problem)
            for problem in detail
        )
    return f"HTTP {response.status_code}"


def _raise_for_refusal(response: httpx.Response) -> None:
    """Raise the typed error for an error answer, before the generated parser runs.

    A 401 passes, so the gateway auth can fetch a new token and send the request
    again; a second 401 reaches ``_parsed`` and is reported as unavailable.
    """
    if response.status_code < httpx.codes.BAD_REQUEST:
        return
    if response.status_code == httpx.codes.UNAUTHORIZED:
        return
    response.read()
    reason = _refusal_reason(response)
    if response.status_code == httpx.codes.NOT_FOUND:
        raise SimulationRecordNotFoundError(reason)
    if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
        raise SimulationRequestRefusedError(reason)
    msg = (
        f"the Simulation Entrypoint answered HTTP {response.status_code}: "
        f"{reason[:200]}"
    )
    raise SimulationServiceUnavailableError(msg)


def _parsed(call: Callable[[], Response[Any]], expected: type[ParsedT]) -> ParsedT:
    """Run one generated route call and return its parsed success answer.

    Network failures, a gateway token that cannot be fetched, other answers
    and answers that do not parse mean the entrypoint cannot be used now.
    """
    try:
        response = call()
    except (
        SimulationRecordNotFoundError,
        SimulationRequestRefusedError,
        SimulationServiceUnavailableError,
    ):
        raise
    except httpx.HTTPError as error:
        msg = f"the Simulation Entrypoint could not be reached: {type(error).__name__}"
        raise SimulationServiceUnavailableError(msg) from error
    except GatewayAuthError as error:
        msg = f"the gateway token for the Simulation Entrypoint is unavailable: {error}"
        raise SimulationServiceUnavailableError(msg) from error
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        _raise_unreadable(error)
    if not isinstance(response.parsed, expected):
        msg = (
            "the Simulation Entrypoint answered HTTP "
            f"{int(response.status_code)} without the expected body"
        )
        raise SimulationServiceUnavailableError(msg)
    return response.parsed


def _raise_unreadable(error: Exception) -> NoReturn:
    msg = (
        f"the Simulation Entrypoint's answer could not be read: {type(error).__name__}"
    )
    raise SimulationServiceUnavailableError(msg) from error


def _run_error(error: RunErrorResponse | None) -> RunError | None:
    return None if error is None else RunError(code=error.code, message=error.message)


def _simulation(simulation: SimulationResponse) -> SimulationRecord:
    return SimulationRecord(
        id=simulation.id,
        kind=simulation.kind,
        country_id=simulation.country,
        policy_id=simulation.policy_id,
        dynamic_id=simulation.dynamic_id,
        region_code=simulation.region_code,
        dataset_name=simulation.dataset_name,
        legacy_simulation_id=simulation.legacy_simulation_id,
        created_at=simulation.created_at,
    )


def _simulation_run(run: SimulationRunResponse) -> SimulationRunRecord:
    return SimulationRunRecord(
        id=run.id,
        simulation_id=run.simulation_id,
        status=run.status,
        attempt=run.attempt,
        trigger=run.trigger,
        error=_run_error(run.error),
        dispatched_at=run.dispatched_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


def _comparison(comparison: ComparisonResponse) -> ComparisonRecord:
    return ComparisonRecord(
        status=comparison.status,
        error=_run_error(comparison.error),
        dispatched_at=comparison.dispatched_at,
        completed_at=comparison.completed_at,
    )


def _report_run(run: EconomyReportRunResponse) -> EconomyReportRunRecord:
    return EconomyReportRunRecord(
        id=run.id,
        report_id=run.report_id,
        trigger=run.trigger,
        tax_benefit_model_version_id=run.catalog_version_id,
        policyengine_version=run.policyengine_version,
        year=run.year,
        status=ReportStatus(run.status.value),
        stage=None if run.stage is None else run.stage.value,
        error=_run_error(run.error),
        baseline_run=_simulation_run(run.baseline_run),
        reform_run=_simulation_run(run.reform_run),
        comparison=_comparison(run.comparison),
        created_at=run.created_at,
    )


def _report(report: EconomyReportResponse) -> EconomyReportRecord:
    return EconomyReportRecord(
        id=report.id,
        country_id=report.country,
        year=report.year,
        options=report.options.to_dict(),
        legacy_report_id=report.legacy_report_id,
        created_at=report.created_at,
        baseline_simulation=_simulation(report.baseline_simulation),
        reform_simulation=_simulation(report.reform_simulation),
        status=ReportStatus(report.status.value),
        run=None if report.run is None else _report_run(report.run),
        result=None if report.result is None else report.result.to_dict(),
    )


def _simulation_choice(choice: SimulationChoice) -> SimulationChoiceRequest:
    return SimulationChoiceRequest(
        policy_id=choice.policy_id, dynamic_id=choice.dynamic_id
    )


class SimulationEntrypointEconomyReports:
    """``EconomyReportSimulation`` over the generated simulation client."""

    def __init__(self, client: AuthenticatedClient, *, base_url: str) -> None:
        """Send every request through ``client``, whose base URL is ``base_url``."""
        self._client = client
        self.base_url = base_url

    def submit_report(self, submission: EconomyReportSubmission) -> EconomyReportRecord:
        """Create a report and its first run in the entrypoint, and start it."""
        body = EconomyReportSubmissionRequest(
            country=EconomyReportSubmissionRequestCountry(submission.country_id),
            policyengine_version=submission.policyengine_version,
            year=submission.year,
            region_code=submission.region_code,
            baseline=_simulation_choice(submission.baseline),
            reform=_simulation_choice(submission.reform),
            dataset_name=(
                UNSET if submission.dataset_name is None else submission.dataset_name
            ),
        )
        return _report(
            _parsed(
                lambda: submit_economy_report.sync_detailed(
                    client=self._client, body=body
                ),
                EconomyReportResponse,
            )
        )

    def get_report(self, report_id: UUID) -> EconomyReportRecord:
        """Return a report with its newest run and, once succeeded, its result."""
        return _report(
            _parsed(
                lambda: get_economy_report.sync_detailed(
                    report_id, client=self._client
                ),
                EconomyReportResponse,
            )
        )

    def get_report_by_legacy_id(self, legacy_report_id: int) -> EconomyReportRecord:
        """Return the report migrated from a v1 report output number."""
        return _report(
            _parsed(
                lambda: get_economy_report_by_legacy_id.sync_detailed(
                    legacy_report_id, client=self._client
                ),
                EconomyReportResponse,
            )
        )

    def run_report(
        self,
        report_id: UUID,
        *,
        policyengine_version: str,
        trigger: RunTrigger,
        force: bool,
    ) -> EconomyReportRunRecord:
        """Run a report again on the catalog version of ``policyengine_version``."""
        body = EconomyReportRunRequest(
            policyengine_version=policyengine_version,
            trigger=EconomyReportRunRequestTrigger(trigger.value),
            force=force,
        )
        return _report_run(
            _parsed(
                lambda: run_economy_report.sync_detailed(
                    report_id, client=self._client, body=body
                ),
                EconomyReportRunResponse,
            )
        )

    def list_report_runs(self, report_id: UUID) -> tuple[EconomyReportRunRecord, ...]:
        """Return a report's runs, newest first."""
        runs = _parsed(
            lambda: list_economy_report_runs.sync_detailed(
                report_id, client=self._client
            ),
            EconomyReportRunsResponse,
        )
        return tuple(_report_run(run) for run in runs.runs)

    def get_simulation(self, simulation_id: UUID) -> SimulationRecord:
        """Return a simulation."""
        return _simulation(
            _parsed(
                lambda: get_simulation.sync_detailed(
                    simulation_id, client=self._client
                ),
                SimulationResponse,
            )
        )


def simulation_entrypoint_economy_reports(
    base_url: str,
    *,
    auth: httpx.Auth | None,
    transport: httpx.BaseTransport | None = None,
) -> SimulationEntrypointEconomyReports:
    """Build the adapter for the entrypoint at ``base_url``.

    ``auth`` adds the bearer token; ``transport`` replaces the network in tests.
    """
    http_client = httpx.Client(
        base_url=base_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        auth=auth,
        transport=transport,
        event_hooks={
            "request": [attach_request_identifiers],
            "response": [_raise_for_refusal],
        },
    )
    instrument_httpx(http_client, get_runtime())
    # The httpx client carries the refreshing gateway token, so the generated
    # client's own fixed token is never sent.
    client = AuthenticatedClient(base_url=base_url, token="").set_httpx_client(
        http_client
    )
    return SimulationEntrypointEconomyReports(client, base_url=base_url)


def _entrypoint_url() -> str:
    try:
        return required_base_url(SIMULATION_ENTRYPOINT_URL_ENV)
    except ValueError as error:
        raise SimulationServiceUnavailableError(str(error)) from error


def _gateway_auth() -> httpx.Auth | None:
    """Return the gateway bearer auth, or None where it may be left unconfigured."""
    try:
        return gateway_bearer_auth_from_environment()
    except GatewayAuthError as error:
        raise SimulationServiceUnavailableError(str(error)) from error


def economy_reports_from_environment() -> SimulationEntrypointEconomyReports:
    """Build the adapter from ``SIMULATION_ENTRYPOINT_URL`` and the gateway auth.

    Raise ``SimulationServiceUnavailableError`` when either is unusable.
    """
    return simulation_entrypoint_economy_reports(
        _entrypoint_url(), auth=_gateway_auth()
    )


@cache
def shared_economy_reports() -> SimulationEntrypointEconomyReports:
    """Return one adapter per process, so its gateway token is fetched once."""
    return economy_reports_from_environment()
