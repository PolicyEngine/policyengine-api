"""The Simulation Entrypoint's household report routes, through its generated client.

This module and ``policyengine_api.libs.simulation_economy_reports`` are the
only modules that import ``policyengine_api_simulation_client``, the client
generated from the Simulation Entrypoint's OpenAPI document. Everything else
uses ``HouseholdReportSimulation``, which this module implements, so the rest
of the code and its tests do not need the client. Nothing imports this
module at module level, so the application starts without the client
installed and household reports then answer 503.

Requests go to ``SIMULATION_ENTRYPOINT_URL``, the Cloud Run Simulation
Entrypoint, the only one with these routes, with the gateway bearer token
(``simulation:submit`` to submit or run, ``simulation:read`` to read).

The entrypoint names the Public API's stored household and policies by ID and
reads them itself. Its declared answers become the protocol's errors:

- 404 with the entrypoint's own detail: no such report. A 404 whose detail is
  exactly "Not Found" is FastAPI's answer for a route the entrypoint does not
  serve, such as a revision without these routes, so it means the entrypoint
  cannot be used.
- 422: the caller's data it cannot calculate (a parameter the catalog version
  lacks, a stored policy value or household the household functions refuse),
  with its reason, or the request fields it refused.
- 400: a household, policy or catalog version it does not have, or a
  household without a default year. The Public API checks those itself
  before sending, so a 400 means the two services disagree, and the
  entrypoint cannot be used for this request.
- 503, any other answer, an answer that does not parse, no answer or a
  gateway token that cannot be fetched: the entrypoint cannot be used now.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, TypeVar

import httpx
from policyengine_api_simulation_client import AuthenticatedClient
from policyengine_api_simulation_client.api.default import (
    get_household_report,
    run_household_report,
    submit_household_report,
)
from policyengine_api_simulation_client.models import (
    HouseholdPolicyChoice as GeneratedPolicyChoice,
)
from policyengine_api_simulation_client.models import (
    HouseholdRefusalResponse,
    HouseholdReportResponse,
    HouseholdReportRunSubmission,
    HouseholdReportSubmissionCountry,
    HouseholdRequestFieldError,
    HouseholdRouteError,
)
from policyengine_api_simulation_client.models import (
    HouseholdReportSubmission as GeneratedSubmission,
)
from policyengine_api_simulation_client.models import (
    RunTrigger as GeneratedRunTrigger,
)
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
from policyengine_api.services.v2.household_reports.types import (
    HouseholdCalculationError,
    HouseholdCalculationOutput,
    HouseholdCalculationRecord,
    HouseholdReportRecord,
    HouseholdReportRunRecord,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ReportStatus,
    SimulationRecordNotFoundError,
    SimulationRequestRefusedError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from policyengine_api_simulation_client.models import (
        HouseholdCalculationResponse,
    )
    from policyengine_api_simulation_client.types import Response

    from policyengine_api.services.v2.household_reports.types import (
        HouseholdPolicyChoice,
        HouseholdReportSubmission,
    )
    from policyengine_api.services.v2.simulation_entrypoint.types import (
        RunTrigger,
    )

SIMULATION_ENTRYPOINT_URL_ENV = "SIMULATION_ENTRYPOINT_URL"
# FastAPI's 404 detail for a route the application does not serve.
UNSERVED_ROUTE_DETAIL = "Not Found"
REQUEST_TIMEOUT_SECONDS = 30.0
# A run claimed but not yet started on Modal is still waiting to run.
REPORT_STATUSES = {
    "pending": ReportStatus.PENDING,
    "dispatching": ReportStatus.PENDING,
    "running": ReportStatus.RUNNING,
    "succeeded": ReportStatus.SUCCEEDED,
    "failed": ReportStatus.FAILED,
}
ParsedT = TypeVar("ParsedT")


def _raise_unusable(detail: str) -> NoReturn:
    msg = f"the Simulation Entrypoint cannot serve household reports: {detail}"
    raise SimulationServiceUnavailableError(msg)


def _refusal_reason(refusal: HouseholdRefusalResponse) -> str:
    """Return a 422's reason: the entrypoint's text, or each refused field.

    A field's location is given without the request's ``body`` prefix. A
    refusal of another shape means the entrypoint cannot be used.
    """
    detail: object = refusal.detail
    if isinstance(detail, str):
        return detail
    if not isinstance(detail, list) or not all(
        isinstance(field_error, HouseholdRequestFieldError) for field_error in detail
    ):
        _raise_unusable("its refusal could not be read")
    reasons = []
    for field_error in detail:
        location = [str(part) for part in field_error.loc]
        if location[:1] == ["body"]:
            location = location[1:]
        reasons.append(f"{'.'.join(location)}: {field_error.msg}")
    return "; ".join(reasons) or "the request is invalid"


def _raise_declared_error(status_code: int, answer: object) -> NoReturn:
    """Raise the protocol's error for one of the entrypoint's declared answers."""
    if isinstance(answer, HouseholdRefusalResponse):
        raise SimulationRequestRefusedError(_refusal_reason(answer))
    if (
        isinstance(answer, HouseholdRouteError)
        and status_code == httpx.codes.NOT_FOUND
        and answer.detail != UNSERVED_ROUTE_DETAIL
    ):
        raise SimulationRecordNotFoundError(answer.detail)
    detail = answer.detail[:200] if isinstance(answer, HouseholdRouteError) else ""
    _raise_unusable(f"it answered HTTP {status_code} {detail}".rstrip())


def _parsed(call: Callable[[], Response[Any]], expected: type[ParsedT]) -> ParsedT:
    """Run one generated route call and return its parsed success answer."""
    try:
        response = call()
    except httpx.HTTPError as error:
        msg = f"the Simulation Entrypoint could not be reached: {type(error).__name__}"
        raise SimulationServiceUnavailableError(msg) from error
    except GatewayAuthError as error:
        msg = f"the gateway token for the Simulation Entrypoint is unavailable: {error}"
        raise SimulationServiceUnavailableError(msg) from error
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        msg = (
            "the Simulation Entrypoint's answer could not be read: "
            f"{type(error).__name__}"
        )
        raise SimulationServiceUnavailableError(msg) from error
    if isinstance(response.parsed, expected):
        return response.parsed
    _raise_declared_error(int(response.status_code), response.parsed)


class _GeneratedObject(Protocol):
    """A generated model of a free-form JSON object."""

    def to_dict(self) -> dict[str, Any]:
        """Return the object as decoded, in its key order."""
        ...


def _optional_object(value: _GeneratedObject | None) -> dict[str, Any] | None:
    return None if value is None else value.to_dict()


def _calculation(
    calculation: HouseholdCalculationResponse,
) -> HouseholdCalculationRecord:
    result, failure = calculation.result, calculation.error
    return HouseholdCalculationRecord(
        id=calculation.calculation_id,
        simulation_id=calculation.simulation_id,
        policy_id=calculation.policy_id,
        status=calculation.status.value,
        attempt=calculation.attempt,
        trigger=calculation.trigger.value,
        error=(
            None
            if failure is None
            else HouseholdCalculationError(
                code=failure.code,
                message=failure.message,
                detail=_optional_object(failure.detail),
            )
        ),
        result=(
            None
            if result is None
            else HouseholdCalculationOutput(
                household=result.household.to_dict(),
                warnings=tuple(result.warnings),
                spm_config=_optional_object(result.spm_config),
                spm_provenance=_optional_object(result.spm_provenance),
            )
        ),
        dispatched_at=calculation.dispatched_at,
        completed_at=calculation.completed_at,
        created_at=calculation.created_at,
    )


def _report_run(report: HouseholdReportResponse) -> HouseholdReportRunRecord | None:
    """Return the report's run, or None before its first run."""
    if (
        report.report_run_id is None
        or report.catalog_version_id is None
        or report.trigger is None
        or report.status is None
        or report.baseline is None
    ):
        return None
    return HouseholdReportRunRecord(
        id=report.report_run_id,
        report_id=report.report_id,
        trigger=report.trigger.value,
        tax_benefit_model_version_id=report.catalog_version_id,
        policyengine_version=None,
        year=report.year,
        status=REPORT_STATUSES[report.status.value],
        baseline=_calculation(report.baseline),
        reform=None if report.reform is None else _calculation(report.reform),
    )


def _report(report: HouseholdReportResponse) -> HouseholdReportRecord:
    run = _report_run(report)
    return HouseholdReportRecord(
        id=report.report_id,
        country_id=report.country,
        year=report.year,
        household_id=report.household_id,
        baseline_simulation_id=report.baseline_simulation_id,
        reform_simulation_id=report.reform_simulation_id,
        status=ReportStatus.NOT_RUN if run is None else run.status,
        run=run,
    )


def _policy_choice(choice: HouseholdPolicyChoice) -> GeneratedPolicyChoice:
    return GeneratedPolicyChoice(policy_id=choice.policy_id)


class SimulationEntrypointHouseholdReports:
    """``HouseholdReportSimulation`` over the generated simulation client."""

    def __init__(self, client: AuthenticatedClient, *, base_url: str) -> None:
        """Send every request through ``client``, whose base URL is ``base_url``."""
        self._client = client
        self.base_url = base_url

    def submit_report(
        self, submission: HouseholdReportSubmission
    ) -> HouseholdReportRecord:
        """Create a report and its first run in the entrypoint, and start it."""
        body = GeneratedSubmission(
            country=HouseholdReportSubmissionCountry(submission.country_id),
            policyengine_version=submission.policyengine_version,
            household_id=submission.household_id,
            baseline=_policy_choice(submission.baseline),
            reform=(
                None if submission.reform is None else _policy_choice(submission.reform)
            ),
            trigger=GeneratedRunTrigger.INITIAL,
        )
        return _report(
            _parsed(
                lambda: submit_household_report.sync_detailed(
                    client=self._client, body=body
                ),
                HouseholdReportResponse,
            )
        )

    def get_report(self, report_id: UUID) -> HouseholdReportRecord:
        """Return a report with its newest run and that run's calculations."""
        return _report(
            _parsed(
                lambda: get_household_report.sync_detailed(
                    report_id, client=self._client
                ),
                HouseholdReportResponse,
            )
        )

    def run_report(
        self,
        report_id: UUID,
        *,
        policyengine_version: str,
        trigger: RunTrigger,
        force: bool,
    ) -> HouseholdReportRecord:
        """Start another run of a report and return the report with that run."""
        body = HouseholdReportRunSubmission(
            policyengine_version=policyengine_version,
            trigger=GeneratedRunTrigger(trigger.value),
            force=force,
        )
        return _report(
            _parsed(
                lambda: run_household_report.sync_detailed(
                    report_id, client=self._client, body=body
                ),
                HouseholdReportResponse,
            )
        )


def simulation_entrypoint_household_reports(
    base_url: str,
    *,
    auth: httpx.Auth | None,
    transport: httpx.BaseTransport | None = None,
) -> SimulationEntrypointHouseholdReports:
    """Build the adapter for the entrypoint at ``base_url``.

    ``auth`` adds the bearer token; ``transport`` replaces the network in tests.
    """
    http_client = httpx.Client(
        base_url=base_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        auth=auth,
        transport=transport,
        event_hooks={"request": [attach_request_identifiers]},
    )
    instrument_httpx(http_client, get_runtime())
    # The httpx client carries the refreshing gateway token, so the generated
    # client's own fixed token is never sent.
    client = AuthenticatedClient(base_url=base_url, token="").set_httpx_client(
        http_client
    )
    return SimulationEntrypointHouseholdReports(client, base_url=base_url)


def household_reports_from_environment() -> SimulationEntrypointHouseholdReports:
    """Build the adapter from ``SIMULATION_ENTRYPOINT_URL`` and the gateway auth.

    Raise ``SimulationServiceUnavailableError`` when either is unusable.
    """
    try:
        base_url = required_base_url(SIMULATION_ENTRYPOINT_URL_ENV)
        auth = gateway_bearer_auth_from_environment()
    except (ValueError, GatewayAuthError) as error:
        raise SimulationServiceUnavailableError(str(error)) from error
    return simulation_entrypoint_household_reports(base_url, auth=auth)


@cache
def shared_household_reports() -> SimulationEntrypointHouseholdReports:
    """Return one adapter per process, so its gateway token is fetched once."""
    return household_reports_from_environment()
