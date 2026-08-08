import json
from flask import Response, request
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
import logging
from datetime import date
from policyengine_api.utils.deprecated_inputs import drop_deprecated_inputs
from policyengine_api.utils.input_validation import (
    find_unrecognized_inputs,
    format_unrecognized_inputs_message,
)
from policyengine_api.utils.payload_validators import validate_country
from policyengine_core.errors import SituationParsingError
from sqlalchemy import select

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import ComputedHousehold, Household, Policy


def get_countries():
    from policyengine_api.country import COUNTRIES

    return COUNTRIES


def add_yearly_variables(household, country_id, countries=None):
    """
    Add yearly variables to a household dict before enqueueing calculation
    """
    metadata = (countries or get_countries()).get(country_id).metadata

    variables = metadata["variables"]
    entities = metadata["entities"]
    household_year = get_household_year(household)

    for variable in variables:
        if variables[variable]["definitionPeriod"] in (
            "year",
            "month",
            "eternity",
        ):
            entity_plural = entities[variables[variable]["entity"]]["plural"]
            if entity_plural in household:
                possible_entities = household[entity_plural].keys()
                for entity in possible_entities:
                    if (
                        variables[variable]["name"]
                        not in household[entity_plural][entity]
                    ):
                        if variables[variable]["isInputVariable"]:
                            household[entity_plural][entity][
                                variables[variable]["name"]
                            ] = {household_year: variables[variable]["defaultValue"]}
                        else:
                            household[entity_plural][entity][
                                variables[variable]["name"]
                            ] = {household_year: None}
    return household


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


def get_household_year(household):
    """Given a household dict, get the household's year

    Args:
        household (dict): The household itself
    """

    # Set household_year based on current year
    household_year = date.today().year

    # Determine if "age" variable present within household and return list of values at it
    household_age_list = list(
        household.get("people", {}).get("you", {}).get("age", {}).keys()
    )
    # If it is, overwrite household_year with the value present
    if len(household_age_list) > 0:
        household_year = household_age_list[0]

    return household_year


@validate_country
def get_household_under_policy(country_id: str, household_id: str, policy_id: str):
    """Get a household's output data under a given policy.

    Args:
        country_id (str): The country ID.
        household_id (str): The household ID.
        policy_id (str): The policy ID.
    """

    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

    # Look in computed_households to see if already computed

    sessions = get_v1_session_factory(local=True)
    with sessions() as session:
        computed_household = session.scalar(
            select(ComputedHousehold).where(
                ComputedHousehold.household_id == int(household_id),
                ComputedHousehold.policy_id == int(policy_id),
                ComputedHousehold.country_id == country_id,
                ComputedHousehold.api_version == api_version,
            )
        )

    if computed_household is not None:
        return dict(
            status="ok",
            message=None,
            result=computed_household.computed_household_json,
        )

    # Retrieve from the household table

    sessions = get_v1_session_factory()
    with sessions() as session:
        household = session.scalar(
            select(Household).where(
                Household.country_id == country_id,
                Household.id == int(household_id),
            )
        )
        policy = session.scalar(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.id == int(policy_id),
            )
        )

    if household is None:
        response_body = dict(
            status="error",
            message=f"Household #{household_id} not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )

    # Add in any missing yearly variables
    household_json = add_yearly_variables(
        household.household_json,
        country_id,
    )
    deprecated_inputs = drop_deprecated_inputs(household_json)
    household_json = deprecated_inputs.household

    # Retrieve from the policy table

    if policy is None:
        response_body = dict(
            status="error",
            message=f"Policy #{policy_id} not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )

    country = get_countries().get(country_id)
    invalid_inputs_response = get_invalid_inputs_response(
        household_json,
        policy.policy_json,
        country,
    )
    if invalid_inputs_response is not None:
        return invalid_inputs_response

    try:
        result = country.calculate(
            household_json,
            policy.policy_json,
            household_id,
            policy_id,
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

    # Store the result in the computed_household table

    with get_v1_session_factory(local=True).begin() as session:
        identity = (int(household_id), int(policy_id), country_id)
        computed_household = session.get(ComputedHousehold, identity)
        if computed_household is None:
            computed_household = ComputedHousehold(
                country_id=country_id,
                household_id=int(household_id),
                policy_id=int(policy_id),
                computed_household_json=result,
                api_version=api_version,
                status="complete",
            )
            session.add(computed_household)
        else:
            computed_household.computed_household_json = result
            computed_household.api_version = api_version
            computed_household.status = "complete"

    response_body = dict(
        status="ok",
        message=None,
        result=result,
    )
    warning_messages = [w.message for w in deprecated_inputs.warnings]
    if warning_messages:
        response_body["warnings"] = warning_messages
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
        result = country.calculate(household_json, policy_json)
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
