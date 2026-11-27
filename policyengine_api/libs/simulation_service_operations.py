"""Send API v1's requests to the simulation service through its generated client.

``policyengine-api-simulation-client`` is generated from the simulation
service's OpenAPI document. ``pyproject.toml`` pins it to a release whose
request models hold every field API v1 sends. Each function here sends one
route's request:

1. it builds the route's generated request model from the body API v1
   builds (``from_dict``);
2. the route's generated operation builds the request from that model: its
   method, path, JSON body and content type;
3. it sends the request on ``http_client``, which
   ``simulation_service_http_client``
   (``policyengine_api.libs.simulation_service_answers``) builds with the
   service's base URL, gateway credentials, request and observability ID
   headers, transport and instrumentation;
4. it returns the answer's status and body unread. The calling module reads
   them.

Each generated operation builds its request with ``_get_kwargs``, and these
functions call it rather than the operation's ``sync_detailed``.
``sync_detailed`` also parses the answer, and raises on a body that isn't
JSON or isn't the shape the route documents, and on a status
``http.HTTPStatus`` doesn't name. API v1 reads those answers itself: a
created record whose answer can't be read, and a 503 that a front end
answers in the service's place, are different errors. The generated parsers
also document only 201 for a created report or re-run, while API v1 reads a
202 as created too.

A generated request model keeps only the fields it defines, so a field
API v1 sends that the pinned release lacks would be dropped.
``tests/unit/libs/test_simulation_generated_client.py`` checks that each
request is the one API v1 builds; run those tests when moving the pin.

To call another of the simulation service's routes, add a function here that
does the same with that route's generated operation and request model, and
call it through ``send_to_simulation_service``
(``policyengine_api.libs.simulation_service_answers``), which turns transport
errors into the simulation service errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from policyengine_api_simulation_client.api.default.create_report import (
    _get_kwargs as report_request_arguments,
)
from policyengine_api_simulation_client.api.default.create_simulation import (
    _get_kwargs as simulation_request_arguments,
)
from policyengine_api_simulation_client.api.default.rerun_report import (
    _get_kwargs as report_rerun_request_arguments,
)
from policyengine_api_simulation_client.api.default.submit_household_calculation import (  # noqa: E501  # a module path can't be split across lines
    _get_kwargs as household_calculation_request_arguments,
)
from policyengine_api_simulation_client.models import (
    BudgetWindowReportRequest,
    EconomyReportRequest,
    EconomySimulationRequest,
    HouseholdCalculationRequest,
    HouseholdReportRequest,
    ReportRerunRequest,
)

from policyengine_api.libs.simulation_service_answers import SimulationAnswer

if TYPE_CHECKING:
    from uuid import UUID

    import httpx

# The generated model of each kind of report sent to POST /reports, by the
# body's report_type.
REPORT_REQUEST_MODELS: dict[
    str,
    type[EconomyReportRequest | BudgetWindowReportRequest | HouseholdReportRequest],
] = {
    "economy": EconomyReportRequest,
    "budget_window": BudgetWindowReportRequest,
    "household": HouseholdReportRequest,
}


def send_operation_request(
    http_client: httpx.Client, request_arguments: dict[str, Any]
) -> SimulationAnswer:
    """Send the request a generated operation built; return its status and body.

    ``request_arguments`` is what the operation's ``_get_kwargs`` returns.
    Raise httpx.HTTPError when no answer arrives, and GatewayAuthError when
    the gateway token cannot be fetched.
    """
    response = http_client.request(**request_arguments)
    return SimulationAnswer(status_code=response.status_code, content=response.content)


def post_household_calculation(
    http_client: httpx.Client, body: dict[str, Any]
) -> SimulationAnswer:
    """Send one household calculation (``POST /household-calculations``).

    Raise what ``send_operation_request`` raises.
    """
    request = HouseholdCalculationRequest.from_dict(body)
    return send_operation_request(
        http_client, household_calculation_request_arguments(body=request)
    )


def post_simulation(
    http_client: httpx.Client, body: dict[str, Any]
) -> SimulationAnswer:
    """Send one economy simulation (``POST /simulations``).

    Raise what ``send_operation_request`` raises.
    """
    request = EconomySimulationRequest.from_dict(body)
    return send_operation_request(
        http_client, simulation_request_arguments(body=request)
    )


def post_report(http_client: httpx.Client, body: dict[str, Any]) -> SimulationAnswer:
    """Send one economy report, budget window or household report (``POST /reports``).

    The body's ``report_type`` selects its generated model. Raise what
    ``send_operation_request`` raises.
    """
    request = REPORT_REQUEST_MODELS[body["report_type"]].from_dict(body)
    return send_operation_request(http_client, report_request_arguments(body=request))


def post_report_rerun(
    http_client: httpx.Client, report_id: UUID, body: dict[str, Any]
) -> SimulationAnswer:
    """Send one re-run of a stored report (``POST /reports/{report_id}/runs``).

    Raise what ``send_operation_request`` raises.
    """
    request = ReportRerunRequest.from_dict(body)
    return send_operation_request(
        http_client, report_rerun_request_arguments(report_id, body=request)
    )
