from flask import Blueprint, Response, request
from pydantic import ValidationError
from policyengine_api.query_parameters import (
    AnnualEconomyQuery,
    BUDGET_WINDOW_MAX_YEARS,
    BudgetWindowEconomyQuery,
    parse_multidict_query,
)
from policyengine_api.services.economy_service import (
    EconomyService,
    EconomicImpactResult,
    BudgetWindowEconomicImpactResult,
)
from policyengine_api.response_factory import _make_error_response
from policyengine_api.utils import get_current_law_policy_id
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.spm import (
    SPMValidationError,
    readable_validation_error,
    spm_error_detail,
)
import json

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


@economy_bp.route(
    "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
    methods=["GET"],
)
@validate_country
def get_economic_impact(country_id: str, policy_id: int, baseline_policy_id: int):
    policy_id = int(policy_id or get_current_law_policy_id(country_id))
    baseline_policy_id = int(
        baseline_policy_id or get_current_law_policy_id(country_id)
    )

    try:
        query = parse_multidict_query(AnnualEconomyQuery, request.args)
        economic_impact_result: EconomicImpactResult = (
            economy_service.get_economic_impact(
                country_id=country_id,
                policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=query.region,
                dataset=query.dataset,
                time_period=query.time_period,
                options=query.calculation_options(),
                api_version=query.version or COUNTRY_PACKAGE_VERSIONS.get(country_id),
                target=query.target,
            )
        )
    except ValueError as error:
        return _bad_request_response(error)

    result_dict: dict[str, str | dict | None] = economic_impact_result.to_dict()

    return _json_response(
        {
            "status": result_dict["status"],
            "message": None,
            "result": result_dict["data"],
        }
    )


@economy_bp.route(
    "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>/budget-window",
    methods=["GET"],
)
@validate_country
def get_budget_window_economic_impact(
    country_id: str, policy_id: int, baseline_policy_id: int
):
    policy_id = int(policy_id or get_current_law_policy_id(country_id))
    baseline_policy_id = int(
        baseline_policy_id or get_current_law_policy_id(country_id)
    )

    try:
        query = parse_multidict_query(BudgetWindowEconomyQuery, request.args)
        economic_impact_result: BudgetWindowEconomicImpactResult = (
            economy_service.get_budget_window_economic_impact(
                country_id=country_id,
                policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=query.region,
                dataset=query.dataset,
                start_year=query.start_year,
                window_size=query.window_size,
                options=query.calculation_options(),
                api_version=query.version or COUNTRY_PACKAGE_VERSIONS.get(country_id),
                target=query.target,
            )
        )
    except ValueError as error:
        return _bad_request_response(error)

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
