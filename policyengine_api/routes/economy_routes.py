from flask import Blueprint, Response, request
from policyengine_api.services.economy_service import (
    EconomyService,
    EconomicImpactResult,
    BudgetWindowEconomicImpactResult,
)
from policyengine_api.utils import get_current_law_policy_id
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
import json
from typing import Literal

economy_bp = Blueprint("economy", __name__)
economy_service = EconomyService()


def _json_response(payload: dict, status: int = 200) -> Response:
    return Response(
        json.dumps(payload),
        status=status,
        mimetype="application/json",
    )


def _bad_request_response(message: str) -> Response:
    return _json_response(
        {
            "status": "error",
            "message": message,
            "result": None,
        },
        status=400,
    )


@validate_country
@economy_bp.route(
    "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
    methods=["GET"],
)
def get_economic_impact(country_id: str, policy_id: int, baseline_policy_id: int):

    policy_id = int(policy_id or get_current_law_policy_id(country_id))
    baseline_policy_id = int(
        baseline_policy_id or get_current_law_policy_id(country_id)
    )

    # Pop items from query params
    query_parameters = request.args
    options = dict(query_parameters)
    options = json.loads(json.dumps(options))
    region = options.pop("region")
    dataset = options.pop("dataset", "default")
    time_period = options.pop("time_period")

    # Handle district breakdowns - only for US national simulations
    include_district_breakdowns_raw = options.pop(
        "include_district_breakdowns", "false"
    )
    include_district_breakdowns = include_district_breakdowns_raw.lower() == "true"
    if include_district_breakdowns and country_id == "us" and region == "us":
        dataset = "national-with-breakdowns"
    target: Literal["general", "cliff"] = options.pop("target", "general")
    api_version = options.pop("version", COUNTRY_PACKAGE_VERSIONS.get(country_id))

    economic_impact_result: EconomicImpactResult = economy_service.get_economic_impact(
        country_id=country_id,
        policy_id=policy_id,
        baseline_policy_id=baseline_policy_id,
        region=region,
        dataset=dataset,
        time_period=time_period,
        options=options,
        api_version=api_version,
        target=target,
    )

    result_dict: dict[str, str | dict | None] = economic_impact_result.to_dict()

    return _json_response(
        {
            "status": result_dict["status"],
            "message": None,
            "result": result_dict["data"],
        }
    )


@validate_country
@economy_bp.route(
    "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>/budget-window",
    methods=["GET"],
)
def get_budget_window_economic_impact(
    country_id: str, policy_id: int, baseline_policy_id: int
):
    policy_id = int(policy_id or get_current_law_policy_id(country_id))
    baseline_policy_id = int(
        baseline_policy_id or get_current_law_policy_id(country_id)
    )

    query_parameters = request.args
    options = dict(query_parameters)
    options = json.loads(json.dumps(options))
    region = options.pop("region", None)
    if not region:
        return _bad_request_response("Missing required query parameter: region")

    dataset = options.pop("dataset", "default")
    start_year = options.pop("start_year", None)
    if not start_year:
        return _bad_request_response("Missing required query parameter: start_year")

    window_size_raw = options.pop("window_size", None)
    if window_size_raw is None:
        return _bad_request_response("Missing required query parameter: window_size")

    try:
        window_size = int(window_size_raw)
    except (TypeError, ValueError):
        return _bad_request_response("window_size must be an integer")

    include_district_breakdowns_raw = options.pop(
        "include_district_breakdowns", "false"
    )
    include_district_breakdowns = include_district_breakdowns_raw.lower() == "true"
    if include_district_breakdowns and country_id == "us" and region == "us":
        dataset = "national-with-breakdowns"

    target: Literal["general", "cliff"] = options.pop("target", "general")
    if target != "general":
        return _bad_request_response(
            "Budget-window calculations only support target=general"
        )

    api_version = options.pop("version", COUNTRY_PACKAGE_VERSIONS.get(country_id))

    try:
        economic_impact_result: BudgetWindowEconomicImpactResult = (
            economy_service.get_budget_window_economic_impact(
                country_id=country_id,
                policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                start_year=start_year,
                window_size=window_size,
                options=options,
                api_version=api_version,
                target=target,
            )
        )
    except ValueError as error:
        return _bad_request_response(str(error))

    result_dict = economic_impact_result.to_dict()

    return _json_response(
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
