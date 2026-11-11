"""Submit household calculations to the simulation service.

``SimulationHouseholdCalculationClient`` is the household calculation
service's ``HouseholdCalculationSubmitter``. It posts a calculation to the
Cloud Run simulation service's ``POST /household-calculations``, at
``SIMULATION_ENTRYPOINT_URL`` whatever ``SIM_ENTRYPOINT`` selects for the
economy routes, through the HTTP client ``SimulationEntrypointClient`` builds:
the same gateway credentials (``GATEWAY_AUTH_*``), request and observability
ID headers, transport and instrumentation as every other simulation call.

The request names the country, the stored household and the stored policy
(null for current law), ``add_missing_variables``, and the axes and SPM
settings only when the caller gave them. The simulation service's answers
are read as follows.

The job was created:

- 202 with the new job's ID and status is the accepted job.

No job of the submission will run, so the service is unavailable
(SimulationServiceUnavailableError, which the route answers 503):

- 400 when a household, policy or catalog version it names does not exist
  (the Public API checks the first two first), with the service's reason;
- 401, 403, 404, 405, 413 and 429, which its authentication, routing,
  body-size and rate limits answer before its route runs;
- its own 503, which names its code, when it is not configured, cannot read
  its manifest or database, or Modal refused the household function's call,
  after which it failed the job it had created at once;
- a connection never made (``ConnectError``, ``ConnectTimeout``,
  ``PoolTimeout``), a gateway token that cannot be fetched, and missing
  configuration.

The caller's data was refused:

- 422 with its reasons (a malformed request, or one its household contract
  refuses), one per field as FastAPI writes them, which reach the caller as
  SimulationServiceInvalidRequestError. A 422 of another shape is
  unavailable.

The job may exist, and no route finds a household job without its ID, so the
message asks the caller to submit the calculation again and says that this
creates a second job if the first request went through (the route answers
502):

- the service failed after it may have created the job: its 500
  (SimulationServiceInternalError), a 202 whose body cannot be read, and any
  status not named above, such as 200, a redirect, 408, 409 or 501
  (SimulationServiceAnswerUnreadableError);
- its answer was lost once the request may have been sent (any other
  transport error, such as a read timeout or a dropped connection), or a
  proxy in front of it answered in its place: a 502 or 504, which the
  service never answers itself, or a 503 without the service's code
  (SimulationServiceAnswerUnreadableError).

The service's own text may hold stored data, and the route needs no account,
so after a 500 or 503, or a status not named above, a message gives only the
service's status and its ``code`` when that is a fixed identifier (lower-case
letters, digits and underscores, starting with a letter, at most 64
characters). The 400 and 422 refusals keep the service's reasons, which name
the caller's own household, policy and fields.

The HTTP client, the sorting of transport errors, the refusal's reason, the
status and code a message gives, and the lost-answer and failure messages
come from ``policyengine_api.libs.simulation_service_answers``, which the
report and simulation client shares.

Each submission carries the request's ID and observability ID headers. The
observability ID is the request's own, else the caller's, else a new one,
which ``submit`` binds in the current context once the Public API's checks
have passed, as the Public API's own household calculations bind one when
they accept a calculation; the simulation service passes it to the household
function. The route reads it from that context and returns it in the
``X-PolicyEngine-Observability-Id`` header of every answer given once the
call was attempted, since a synchronous route runs in a copy of the request
context that the response middleware doesn't see. It is the attempt's ID,
which the service never received after a connection never made or a gateway
token that couldn't be fetched.

Wiring the generated simulation client: ``post_household_calculation`` is the
only code that sends the request, and it returns the status and body, which
the rest of this module reads. Once a ``policyengine-api-simulation-client``
release has the household calculation route, depend on that release and make
the function call the generated operation, as its docstring says.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import ValidationError

from policyengine_api.libs.simulation_service_answers import (
    PROXY_STAND_IN_STATUSES,
    AnswerModel,
    Refusal,
    SimulationAnswer,
    answer_lost,
    created_but_failed,
    fixed_identifier_code,
    parsed_body,
    refusal_reason,
    send_to_simulation_service,
    simulation_service_http_client,
    status_and_code,
    submit_again,
)
from policyengine_api.request_context import start_observability_id
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationAccepted,
    HouseholdJobStatusName,
)
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationInput,
    )

HOUSEHOLD_CALCULATIONS_PATH = "/household-calculations"
UNREADABLE_ANSWER = "The simulation service's answer could not be read."
# Statuses after which no job of the submission runs: the service's
# authentication, routing, body-size and rate limits answer them before its
# route runs, and its own 503 comes before it creates the job, or after it
# failed the job whose call Modal refused. Only the service's own 503, which
# names its code, reaches this set: ``_accepted_job`` first answers a 503
# without one as a proxy's.
STATUSES_AFTER_WHICH_NO_JOB_RUNS = frozenset(
    {
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.METHOD_NOT_ALLOWED,
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.SERVICE_UNAVAILABLE,
    }
)
# The service may have created the job, and no route finds a household job
# without its ID, so each message after which the job may exist ends with
# this.
SUBMIT_AGAIN = submit_again("household calculation", "job")


def _lost_answer(what_happened: str) -> str:
    """Return the message for an answer lost after the request may have arrived.

    ``what_happened`` names what came in place of a readable answer.
    """
    return answer_lost(what_happened, SUBMIT_AGAIN)


def _created_but_failed(status_and_code_text: str) -> str:
    """Return the message for an answer the service sent once the job may exist.

    ``status_and_code_text`` is the service's status, and its code when that
    is a fixed identifier.
    """
    return created_but_failed("household job", status_and_code_text, SUBMIT_AGAIN)


class _AcceptedJob(AnswerModel):
    """The 202 body: the job the simulation service inserted, and its status."""

    job_id: UUID
    status: HouseholdJobStatusName


def household_calculation_request(
    calculation: HouseholdCalculationInput,
) -> dict[str, Any]:
    """Return the simulation service's request body for the calculation.

    ``axes`` and ``spm`` are sent only when the caller gave them; each axis
    and the SPM settings keep only the fields the caller gave.
    """
    body: dict[str, Any] = {
        "country": calculation.country_id,
        "household_id": str(calculation.household_id),
        "policy_id": (
            None if calculation.policy_id is None else str(calculation.policy_id)
        ),
        "add_missing_variables": calculation.add_missing_variables,
    }
    if calculation.axes is not None:
        body["axes"] = [
            [axis.model_dump(mode="json", exclude_unset=True) for axis in group]
            for group in calculation.axes
        ]
    if calculation.spm is not None:
        body["spm"] = calculation.spm.model_dump(mode="json")
    return body


def post_household_calculation(
    http_client: httpx.Client, body: dict[str, Any]
) -> SimulationAnswer:
    """Send one submission to the simulation service and return its answer.

    Raise httpx.HTTPError when no answer arrives, and GatewayAuthError when
    the gateway token cannot be fetched. ``http_client`` has the service's
    base URL. To send through the generated client instead, this body
    becomes, with ``Client`` from ``policyengine_api_simulation_client``,
    ``submit_household_calculation`` from its ``api.default`` package and
    ``HouseholdCalculationRequest`` from its ``models``, the names the
    simulation service's OpenAPI document gives the route::

        client = Client(base_url=str(http_client.base_url))
        client.set_httpx_client(http_client)
        response = submit_household_calculation.sync_detailed(
            client=client, body=HouseholdCalculationRequest.from_dict(body)
        )
        return SimulationAnswer(int(response.status_code), response.content)
    """
    response = http_client.post(HOUSEHOLD_CALCULATIONS_PATH, json=body)
    return SimulationAnswer(status_code=response.status_code, content=response.content)


def _invalid_request_reason(refusal: Refusal) -> str:
    """Return the service's reason, or each refused field and why."""
    return (
        "The simulation service cannot calculate this household: "
        f"{refusal_reason(refusal)}"
    )


@dataclass(frozen=True)
class _ReadAnswer:
    """An answer other than 202, its body parsed once.

    ``code`` is the code the body names when it is a fixed identifier, and
    ``refusal`` its reason or refused fields when the body has that shape.
    """

    status_code: int
    code: str | None
    refusal: Refusal | None

    @property
    def status_and_code(self) -> str:
        """The status, and the code when there is one; never the service's text."""
        return status_and_code(self.status_code, self.code)


def _read_answer(answer: SimulationAnswer) -> _ReadAnswer:
    """Parse the answer's body once; a body that is not JSON reads as none.

    Its ``code`` is read on its own, so a code of another type never makes
    the reason unreadable.
    """
    body = parsed_body(answer)
    try:
        refusal = Refusal.model_validate(body)
    except ValidationError:
        refusal = None
    return _ReadAnswer(answer.status_code, fixed_identifier_code(body), refusal)


def _answered_by_a_proxy(read: _ReadAnswer) -> bool:
    """Whether a proxy in front of the service answered in its place.

    The service never answers 502 or 504 itself, and its own 503 always
    names its code.
    """
    if read.status_code in PROXY_STAND_IN_STATUSES:
        return True
    return read.status_code == HTTPStatus.SERVICE_UNAVAILABLE and read.code is None


def _unavailable(read: _ReadAnswer) -> str:
    """Describe an answer after which no job of the submission runs."""
    return f"The simulation service is unavailable ({read.status_and_code})."


def _refused(read: _ReadAnswer) -> str:
    """Describe a 400: a row the request names, or a function it needs, is missing.

    The service's reason names the caller's own household or policy, so it is
    kept.
    """
    if read.refusal is None or not isinstance(read.refusal.detail, str):
        return (
            f"The simulation service refused the calculation ({read.status_and_code})."
        )
    named_code = "" if read.code is None else f" ({read.code})"
    return (
        f"The simulation service refused the calculation{named_code}: "
        f"{read.refusal.detail}"
    )


class SimulationHouseholdCalculationClient:
    """Submit household calculations to the simulation service."""

    def __init__(
        self,
        http_client: httpx.Client,
        *,
        send: Callable[
            [httpx.Client, dict[str, Any]], SimulationAnswer
        ] = post_household_calculation,
    ) -> None:
        """Send through ``send`` on ``http_client``, which has the service's URL."""
        self._http_client = http_client
        self._send = send

    @classmethod
    def from_environment(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> SimulationHouseholdCalculationClient:
        """Call the configured Cloud Run simulation service with gateway auth.

        ``transport`` replaces the simulation transport, for tests. Raise
        SimulationServiceUnavailableError when ``SIMULATION_ENTRYPOINT_URL``
        is missing or invalid, or gateway auth is partly configured or
        required but unset.
        """
        return cls(simulation_service_http_client(transport=transport))

    def submit(
        self, calculation: HouseholdCalculationInput
    ) -> HouseholdCalculationAccepted:
        """Submit the calculation and return the job the service created.

        Raise SimulationServiceInvalidRequestError with the service's reasons
        when it refuses the caller's data (422);
        SimulationServiceUnavailableError when no job of the submission will
        run (its 400, the statuses it answers before its route runs, its own
        503, a connection never made or a gateway token that cannot be
        fetched); SimulationServiceInternalError when it failed (500); and
        SimulationServiceAnswerUnreadableError when it accepted the
        calculation but its answer cannot be read, it answered any other
        status, its answer was lost after the submission may have reached it,
        or a proxy in front of it answered in its place.
        """
        start_observability_id()
        answer = send_to_simulation_service(
            self._send,
            self._http_client,
            household_calculation_request(calculation),
            submit_again_sentence=SUBMIT_AGAIN,
        )
        return _accepted_job(answer)


def _accepted_job(answer: SimulationAnswer) -> HouseholdCalculationAccepted:
    """Return the job the service's answer accepts, or raise what it means.

    The errors are those ``SimulationHouseholdCalculationClient.submit``
    raises, apart from the transport errors it handles itself.
    """
    if answer.status_code == HTTPStatus.ACCEPTED:
        try:
            accepted = _AcceptedJob.model_validate_json(answer.content)
        except ValidationError as error:
            raise SimulationServiceAnswerUnreadableError(
                _created_but_failed(str(answer.status_code))
            ) from error
        return HouseholdCalculationAccepted(
            calculation_id=accepted.job_id, status=accepted.status
        )
    read = _read_answer(answer)
    if _answered_by_a_proxy(read):
        raise SimulationServiceAnswerUnreadableError(
            _lost_answer(f"a proxy answered {read.status_code}")
        )
    if read.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
        if read.refusal is None:
            raise SimulationServiceUnavailableError(UNREADABLE_ANSWER)
        raise SimulationServiceInvalidRequestError(
            _invalid_request_reason(read.refusal)
        )
    if read.status_code == HTTPStatus.BAD_REQUEST:
        raise SimulationServiceUnavailableError(_refused(read))
    if read.status_code in STATUSES_AFTER_WHICH_NO_JOB_RUNS:
        raise SimulationServiceUnavailableError(_unavailable(read))
    failure = _created_but_failed(read.status_and_code)
    if read.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SimulationServiceInternalError(failure)
    raise SimulationServiceAnswerUnreadableError(failure)


@lru_cache(maxsize=1)
def process_simulation_household_calculation_client() -> (
    SimulationHouseholdCalculationClient
):
    """Return the process's client, built from the environment on first use.

    Its connections and gateway token are reused across requests. A
    configuration error is raised again on the next call, not kept.
    """
    return SimulationHouseholdCalculationClient.from_environment()
