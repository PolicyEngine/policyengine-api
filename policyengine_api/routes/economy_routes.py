"""Flask routes for society-wide economic impacts of a policy against a baseline."""

import json
from http import HTTPStatus

from flask import Blueprint, Response, request
from pydantic import ValidationError

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.libs.simulation_entrypoint_transport import (
    SimulationEntrypointConnectionError,
)
from policyengine_api.query_parameters import (
    BUDGET_WINDOW_MAX_YEARS,
    AnnualEconomyQuery,
    BudgetWindowEconomyQuery,
    parse_multidict_query,
)
from policyengine_api.response_factory import _make_error_response
from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_impact_types import (
    FailedImpactDeletion,
    FailedImpactDeletionOutcome,
)
from policyengine_api.services.economy_service import (
    BudgetWindowEconomicImpactResult,
    EconomicImpactResult,
    EconomyService,
)
from policyengine_api.services.policy_service import PolicyNotFoundError
from policyengine_api.spm import (
    SPMValidationError,
    readable_validation_error,
    spm_error_detail,
)
from policyengine_api.utils import get_current_law_policy_id
from policyengine_api.utils.payload_validators import validate_country

economy_bp = Blueprint("economy", __name__)
economy_service = EconomyService()
BUDGET_WINDOW_CACHE_HEADER = "X-PolicyEngine-Budget-Window-Cache"


def _json_response(payload: dict, status: int = 200) -> Response:
    return Response(
        json.dumps(payload),
        status=status,
        mimetype="application/json",
    )


def _bad_request_response(error: str | ValueError) -> Response:
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        field = first["loc"][0] if first["loc"] else None
        message = readable_validation_error(error)
        if field == "spm":
            error = SPMValidationError("SPM_SETTINGS_INVALID", message)
        else:
            if first["type"] == "missing":
                message = f"Missing required query parameter: {field}"
            elif field == "window_size":
                message = (
                    "window_size must be an integer"
                    if first["type"] not in {"greater_than_equal", "less_than_equal"}
                    else f"window_size must be between 1 and {BUDGET_WINDOW_MAX_YEARS}"
                )
            elif field == "target":
                if error.title == BudgetWindowEconomyQuery.__name__:
                    message = "Budget-window calculations only support target=general"
            elif field is None:
                message = first["msg"].removeprefix("Value error, ")
            error = message
    detail = spm_error_detail(error) if isinstance(error, ValueError) else None
    fields = {"errors": [detail]} if detail is not None else {}
    return _make_error_response(error, 400, result=None, **fields)


def _simulation_unreachable_response(
    error: SimulationEntrypointConnectionError,
    *,
    deletable: bool,
) -> Response:
    """Return 502 when a request to the simulation service got no response.

    Nothing is stored for the calculation, so the next request tries again, and
    ``retry_after_seconds`` is null. ``deletable`` marks a URL that takes a
    DELETE, whose 502 also has a null ``delete_after_seconds``.
    """
    deletion_fields = {"delete_after_seconds": None} if deletable else {}
    return _make_error_response(
        error,
        HTTPStatus.BAD_GATEWAY,
        result=None,
        retry_after_seconds=None,
        **deletion_fields,
    )


def _policy_not_found_response(error: PolicyNotFoundError) -> Response:
    """Return 404 naming each policy that the request's country does not have."""
    policy_ids = " and ".join(f"#{policy_id}" for policy_id in error.policy_ids)
    noun = "Policy" if len(error.policy_ids) == 1 else "Policies"
    return _make_error_response(
        f"{noun} {policy_ids} not found.",
        HTTPStatus.NOT_FOUND,
        result=None,
    )


def _annual_impact_request(
    country_id: str,
    policy_id: int,
    baseline_policy_id: int,
    query: AnnualEconomyQuery,
) -> EconomicImpactRequest:
    """Return the annual impact a GET or DELETE on the economy URL names.

    A policy ID of 0 means current law.
    """
    return EconomicImpactRequest(
        country_id=country_id,
        policy_id=int(policy_id or get_current_law_policy_id(country_id)),
        baseline_policy_id=int(
            baseline_policy_id or get_current_law_policy_id(country_id)
        ),
        region=query.region,
        dataset="default",
        options=query.calculation_options(),
        api_version=query.version or COUNTRY_PACKAGE_VERSIONS.get(country_id),
        target=query.target,
    )


@economy_bp.route(
    "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
    methods=["GET"],
)
@validate_country
def get_economic_impact(
    country_id: str, policy_id: int, baseline_policy_id: int
) -> Response:
    """Return the single-year economic impact, starting it if none is cached.

    A policy ID of 0 means current law. The result stays ``computing`` until the
    simulation finishes, and while computing the body also carries the stage
    fields the Simulation Entrypoint reports. Invalid query parameters give 400,
    a policy ID the country does not have gives 404, and a failed calculation,
    or a request to the simulation service that gets no response (after one
    retry if its connection broke), gives 502. One request is an exception:
    for a finished stored impact, the route asks the simulation service which
    worker app the request resolves to, to check whether the impact is out of
    date, and if that request gets no response it answers from the stored
    impact as it is.
    A 502 body's ``retry_after_seconds`` is how long the Public API keeps
    returning the stored failure before a request starts a new run, or null
    when no failure is stored, the next request would answer from a newer
    job, or the failure's lifetime cannot be read. It is the longest wait: a
    deploy that changes the versions or worker app a request resolves to lets
    a request start a new run sooner. Its ``delete_after_seconds`` is how
    long until a DELETE on this URL may remove the stored failure, 0 once it
    may, and null whenever ``retry_after_seconds`` is null.
    """
    try:
        query = parse_multidict_query(AnnualEconomyQuery, request.args)
        economic_impact_result: EconomicImpactResult = (
            economy_service.get_economic_impact(
                impact_request=_annual_impact_request(
                    country_id, policy_id, baseline_policy_id, query
                ),
                time_period=query.time_period,
            )
        )
    except ValueError as error:
        return _bad_request_response(error)
    except PolicyNotFoundError as error:
        return _policy_not_found_response(error)
    except SimulationEntrypointConnectionError as error:
        return _simulation_unreachable_response(error, deletable=True)

    result_dict: dict[str, str | dict | int | None] = economic_impact_result.to_dict()

    if result_dict["status"] == "error":
        return _make_error_response(
            result_dict["message"],
            HTTPStatus.BAD_GATEWAY,
            result=None,
            retry_after_seconds=result_dict.get("retry_after_seconds"),
            delete_after_seconds=result_dict.get("delete_after_seconds"),
        )

    body = {
        "status": result_dict["status"],
        "message": None,
        "result": result_dict["data"],
    }
    # Stage fields from the Simulation Entrypoint, only while computing and
    # only when the entrypoint reports them, so other bodies keep their shape.
    if (
        result_dict["status"] == "computing"
        and economic_impact_result.run_progress is not None
    ):
        body.update(economic_impact_result.run_progress.to_dict())
    return _json_response(body)


@economy_bp.route(
    "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
    methods=["DELETE"],
)
@validate_country
def delete_failed_economic_impact(
    country_id: str, policy_id: int, baseline_policy_id: int
) -> Response:
    """Remove the stored failure a GET on this URL answers from.

    The query is the GET's, parsed by the same model, so it names the same
    stored record. 204 with no body when the record was a failure recorded
    at least 10 seconds ago and is now removed, so the next GET submits a new
    job. 409 when it is a more recent failure, with ``delete_after_seconds``
    until it may be removed, or when it is computing or complete, with
    ``delete_after_seconds`` null. 404 when nothing is stored that the GET
    would answer from; a cache, or a record, that cannot be read gives 500,
    never 404. Invalid query parameters give 400,
    as for the GET, and a request to the simulation service that gets no
    response gives 502.
    """
    try:
        query = parse_multidict_query(AnnualEconomyQuery, request.args)
        deletion: FailedImpactDeletion = economy_service.delete_failed_economic_impact(
            impact_request=_annual_impact_request(
                country_id, policy_id, baseline_policy_id, query
            ),
            time_period=query.time_period,
        )
    except ValueError as error:
        return _bad_request_response(error)
    except SimulationEntrypointConnectionError as error:
        return _make_error_response(error, HTTPStatus.BAD_GATEWAY, result=None)

    if deletion.outcome == FailedImpactDeletionOutcome.DELETED:
        return Response(status=HTTPStatus.NO_CONTENT)
    if deletion.outcome == FailedImpactDeletionOutcome.NOT_FOUND:
        return _make_error_response(deletion.message, HTTPStatus.NOT_FOUND, result=None)
    return _make_error_response(
        deletion.message,
        HTTPStatus.CONFLICT,
        result=None,
        delete_after_seconds=deletion.delete_after_seconds,
    )


@economy_bp.route(
    "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>/budget-window",
    methods=["GET"],
)
@validate_country
def get_budget_window_economic_impact(
    country_id: str, policy_id: int, baseline_policy_id: int
) -> Response:
    """Return a multi-year budget-window impact with per-year progress.

    The body lists completed, computing and queued years, and the
    ``X-PolicyEngine-Budget-Window-Cache`` header reports the cache outcome when
    known. Invalid query parameters give 400, a policy ID the country does
    not have gives 404, and a request to the simulation service that gets no
    response (after one retry if its connection broke) gives 502; a failed
    calculation is reported in the body with status 200.
    """
    policy_id = int(policy_id or get_current_law_policy_id(country_id))
    baseline_policy_id = int(
        baseline_policy_id or get_current_law_policy_id(country_id)
    )

    try:
        query = parse_multidict_query(BudgetWindowEconomyQuery, request.args)
        economic_impact_result: BudgetWindowEconomicImpactResult = (
            economy_service.get_budget_window_economic_impact(
                impact_request=EconomicImpactRequest(
                    country_id=country_id,
                    policy_id=policy_id,
                    baseline_policy_id=baseline_policy_id,
                    region=query.region,
                    dataset="default",
                    options=query.calculation_options(),
                    api_version=query.version
                    or COUNTRY_PACKAGE_VERSIONS.get(country_id),
                    target=query.target,
                ),
                start_year=query.start_year,
                window_size=query.window_size,
            )
        )
    except ValueError as error:
        return _bad_request_response(error)
    except PolicyNotFoundError as error:
        return _policy_not_found_response(error)
    except SimulationEntrypointConnectionError as error:
        return _simulation_unreachable_response(error, deletable=False)

    result_dict = economic_impact_result.to_dict()

    response = _json_response(
        {
            "status": result_dict["status"],
            "message": result_dict["message"],
            "result": result_dict["data"],
            "progress": result_dict["progress"],
            "completed_years": result_dict["completed_years"],
            "computing_years": result_dict["computing_years"],
            "queued_years": result_dict["queued_years"],
            "error": result_dict["error"],
        }
    )
    cache_status = getattr(economic_impact_result, "cache_status", None)
    if isinstance(cache_status, str) and cache_status:
        response.headers[BUDGET_WINDOW_CACHE_HEADER] = cache_status
    return response
