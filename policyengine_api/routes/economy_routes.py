from flask import Blueprint, Response, request
from policyengine_api.services.economy_service import (
    EconomyService,
    EconomicImpactResult,
)
from policyengine_api.utils import get_current_law_policy_id
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
import json
from typing import Literal

economy_bp = Blueprint("economy", __name__)
economy_service = EconomyService()


@validate_country
@economy_bp.route(
    "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
    methods=["GET"],
)
def get_economic_impact(
    country_id: str, policy_id: int, baseline_policy_id: int
):

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
    target: Literal["general", "cliff"] = options.pop("target", "general")
    api_version = options.pop(
        "version", COUNTRY_PACKAGE_VERSIONS.get(country_id)
    )

    economic_impact_result: EconomicImpactResult = (
        economy_service.get_economic_impact(
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
    )

    result_dict: dict[str, str | dict | None] = (
        economic_impact_result.to_dict()
    )

    return Response(
        json.dumps(
            {
                "status": result_dict["status"],
                "message": None,
                "result": result_dict["data"],
            }
        ),
        status=200,
        mimetype="application/json",
    )
