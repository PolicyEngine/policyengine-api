from flask import Blueprint
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.utils import get_current_law_policy_id
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from flask import request, Response
import json
from policyengine_api.utils import Logger

economy_bp = Blueprint("economy", __name__)
economy_service = EconomyService()

logger = Logger()


@validate_country
@economy_bp.route("/<policy_id>/over/<baseline_policy_id>", methods=["GET"])
def get_economic_impact(country_id, policy_id, baseline_policy_id):
    logger.log(
        f"GET request received for get_economic_impact",
        context={
            "country_id": country_id,
            "policy_id": policy_id,
            "baseline_policy_id": baseline_policy_id,
        },
    )

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
    api_version = options.pop(
        "version", COUNTRY_PACKAGE_VERSIONS.get(country_id)
    )

    try:
        result = economy_service.get_economic_impact(
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            options,
            api_version,
        )
        return result
    except Exception as e:
        logger.error(
            f"Error within get_economic_impact",
            context={
                "country_id": country_id,
                "policy_id": policy_id,
                "baseline_policy_id": baseline_policy_id,
                "error": str(e),
            },
        )
        return Response(
            {
                "status": "error",
                "message": "An error occurred while calculating the economic impact. Details: "
                + str(e),
                "result": None,
            },
            500,
        )
