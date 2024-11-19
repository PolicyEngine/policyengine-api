from flask import Blueprint
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.helpers import (
    validate_country,
    get_current_law_policy_id,
)
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from flask import request, Response
import json

economy_bp = Blueprint("economy", __name__)
economy_service = EconomyService()


@economy_bp.route("/<policy_id>/over/<baseline_policy_id>", methods=["GET"])
def get_economic_impact(country_id, policy_id, baseline_policy_id):

    print(f"Got request for {country_id} {policy_id} {baseline_policy_id}")
    # Validate inbound data
    invalid_country = validate_country(country_id)
    if invalid_country:
        return invalid_country

    policy_id = int(policy_id or get_current_law_policy_id(country_id))
    baseline_policy_id = int(
        baseline_policy_id or get_current_law_policy_id(country_id)
    )

    # Pop items from query params
    query_parameters = request.args
    options = dict(query_parameters)
    options = json.loads(json.dumps(options))
    region = options.pop("region")
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
            time_period,
            options,
            api_version,
        )
        return result
    except Exception as e:
        return (
            dict(
                status="error",
                message="An error occurred while calculating the economic impact. Details: "
                + str(e),
                result=None,
            ),
            500,
        )

    # Run service to check if already calculated in local db

    # Service to
