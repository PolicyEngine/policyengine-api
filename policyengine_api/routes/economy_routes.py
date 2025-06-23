from flask import Blueprint
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.utils import get_current_law_policy_id
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from flask import request
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

    result = economy_service.get_economic_impact(
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
    return result
