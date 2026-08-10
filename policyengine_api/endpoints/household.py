import json
from flask import Response, request
import logging
from policyengine_api.utils.deprecated_inputs import drop_deprecated_inputs
from policyengine_api.utils.input_validation import (
    find_unrecognized_inputs,
    format_unrecognized_inputs_message,
)
from policyengine_api.utils.payload_validators import validate_country
from policyengine_core.errors import SituationParsingError

from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
    HouseholdNotFoundError,
    InvalidHouseholdInputsError,
    PolicyNotFoundError,
    add_yearly_variables,
)


household_calculation_service = HouseholdCalculationService()


def get_countries():
    from policyengine_api.country import COUNTRIES

    return COUNTRIES


def get_invalid_inputs_response(household_json, policy_json, country):
    invalid_inputs = find_unrecognized_inputs(
        household_json,
        policy_json,
        country.metadata,
    )
    if not invalid_inputs:
        return None

    response_body = dict(
        status="error",
        message=format_unrecognized_inputs_message(invalid_inputs),
        result=None,
        errors=[invalid_input.to_dict() for invalid_input in invalid_inputs],
    )
    return Response(
        json.dumps(response_body),
        status=400,
        mimetype="application/json",
    )


@validate_country
def get_household_under_policy(country_id: str, household_id: str, policy_id: str):
    """Get a household's output data under a given policy.

    Args:
        country_id (str): The country ID.
        household_id (str): The household ID.
        policy_id (str): The policy ID.
    """

    try:
        calculation = household_calculation_service.calculate_stored_household(
            country_id,
            int(household_id),
            int(policy_id),
        )
    except HouseholdNotFoundError:
        response_body = dict(
            status="error",
            message=f"Household #{household_id} not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )

    except PolicyNotFoundError:
        response_body = dict(
            status="error",
            message=f"Policy #{policy_id} not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )

    except InvalidHouseholdInputsError as error:
        response_body = dict(
            status="error",
            message=format_unrecognized_inputs_message(error.invalid_inputs),
            result=None,
            errors=[invalid_input.to_dict() for invalid_input in error.invalid_inputs],
        )
        return Response(
            json.dumps(response_body),
            status=400,
            mimetype="application/json",
        )
    except Exception as e:
        logging.exception(e)
        response_body = dict(
            status="error",
            message=f"Error calculating household #{household_id} under policy #{policy_id}: {e}",
        )
        return Response(
            json.dumps(response_body),
            status=500,
            mimetype="application/json",
        )

    response_body = dict(
        status="ok",
        message=None,
        result=calculation.household,
    )
    if calculation.warnings:
        response_body["warnings"] = list(calculation.warnings)
    return response_body


@validate_country
def get_calculate(country_id: str, add_missing: bool = False) -> dict:
    """Lightweight endpoint for passing in household and policy JSON objects and calculating without storing data.

    Args:
        country_id (str): The country ID.
    """

    payload = request.json
    household_json = payload.get("household", {})
    policy_json = payload.get("policy", {})

    if add_missing:
        # Add in any missing yearly variables to household_json
        household_json = add_yearly_variables(household_json, country_id)

    # Strip deprecated inputs from a copy before the engine runs so
    # partners who still pass removed/renamed variables get a warning +
    # working response instead of a `VariableNotFoundError` HTTP 500.
    deprecated_inputs = drop_deprecated_inputs(household_json)
    household_json = deprecated_inputs.household
    deprecation_warnings = deprecated_inputs.warnings

    country = get_countries().get(country_id)
    invalid_inputs_response = get_invalid_inputs_response(
        household_json,
        policy_json,
        country,
    )
    if invalid_inputs_response is not None:
        return invalid_inputs_response

    try:
        calculation = country.calculate(household_json, policy_json)
        result = calculation if isinstance(calculation, dict) else calculation.household
    except SituationParsingError as e:
        # Malformed household payloads (e.g. a dict where a number belongs)
        # are client errors, not server errors — mostly bot traffic.
        response_body = dict(
            status="error",
            message=f"Invalid household payload: {e}",
            result=None,
        )
        return Response(
            json.dumps(response_body),
            status=400,
            mimetype="application/json",
        )
    except Exception as e:
        logging.exception(e)
        response_body = dict(
            status="error",
            message=f"Error calculating household under policy: {e}",
        )
        return Response(
            json.dumps(response_body),
            status=500,
            mimetype="application/json",
        )

    response_body = dict(
        status="ok",
        message=None,
        result=result,
    )

    warning_messages = [w.message for w in deprecation_warnings]
    if warning_messages:
        # Serialize to strings on the wire; the structured dataclasses
        # stay available for any future caller that wants the fields.
        response_body["warnings"] = warning_messages

    return response_body
