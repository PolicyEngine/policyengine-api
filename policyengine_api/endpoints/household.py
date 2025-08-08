from policyengine_api.country import (
    COUNTRIES,
)
from policyengine_api.data import database, local_database
import json
from flask import Response, request
from policyengine_api.utils import hash_object
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
import sqlalchemy.exc
from policyengine_api.country import COUNTRIES
import json
import logging
from datetime import date
from policyengine_api.structured_logger import get_logger, log_struct

logger = get_logger()
from policyengine_api.utils.payload_validators import validate_country


def add_yearly_variables(household, country_id):
    """
    Add yearly variables to a household dict before enqueueing calculation
    """
    metadata = COUNTRIES.get(country_id).metadata

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
                        not variables[variable]["name"]
                        in household[entity_plural][entity]
                    ):
                        if variables[variable]["isInputVariable"]:
                            household[entity_plural][entity][
                                variables[variable]["name"]
                            ] = {
                                household_year: variables[variable][
                                    "defaultValue"
                                ]
                            }
                        else:
                            household[entity_plural][entity][
                                variables[variable]["name"]
                            ] = {household_year: None}
    return household


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
def get_household_under_policy(
    country_id: str, household_id: str, policy_id: str
):
    """Get a household's output data under a given policy.

    Args:
        country_id (str): The country ID.
        household_id (str): The household ID.
        policy_id (str): The policy ID.
    """

    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

    # Log start of request
    log_struct(
        event="get_household_under_policy_start",
        input_data={
            "country_id": country_id,
            "household_id": household_id,
            "policy_id": policy_id,
            "api_version": api_version,
            "request_path": request.path,
        },
        message="Started processing household under policy request.",
        severity="INFO",
        logger=logger,  # optional if you've already called get_logger()
    )

    # Look in computed_household cache table
    try:
        row = local_database.query(
            f"SELECT * FROM computed_household WHERE household_id = ? AND policy_id = ? AND api_version = ?",
            (household_id, policy_id, api_version),
        ).fetchone()
    except Exception as e:
        log_struct(
            event="computed_household_query_failed",
            input_data={
                "household_id": household_id,
                "policy_id": policy_id,
                "api_version": api_version,
            },
            message=f"Database query failed: {e}",
            severity="ERROR",
        )
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "message": "Internal server error while querying computed_household.",
                }
            ),
            status=500,
            mimetype="application/json",
        )

    if row is not None:
        log_struct(
            event="cached_computed_household_found",
            input_data={
                "household_id": household_id,
                "policy_id": policy_id,
                "api_version": api_version,
            },
            message="Found precomputed household result in cache.",
            severity="INFO",
        )

        result = dict(
            policy_id=row["policy_id"],
            household_id=row["household_id"],
            country_id=row["country_id"],
            api_version=row["api_version"],
            computed_household_json=row["computed_household_json"],
            status=row["status"],
        )
        result["result"] = json.loads(result["computed_household_json"])
        del result["computed_household_json"]
        return dict(
            status="ok",
            message=None,
            result=result["result"],
        )

    # Retrieve from the household table

    row = database.query(
        f"SELECT * FROM household WHERE id = ? AND country_id = ?",
        (household_id, country_id),
    ).fetchone()

    if row is not None:
        household = dict(row)
        household["household_json"] = json.loads(household["household_json"])
        log_struct(
            event="household_data_loaded",
            input_data={
                "household_id": household_id,
                "country_id": country_id,
            },
            message="Loaded household data from DB.",
            severity="INFO",
        )

    else:
        log_struct(
            event="household_not_found",
            input_data={
                "household_id": household_id,
                "country_id": country_id,
            },
            message=f"Household #{household_id} not found.",
            severity="WARNING",
        )

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
    household["household_json"] = add_yearly_variables(
        household["household_json"], country_id
    )

    # Retrieve from the policy table

    row = database.query(
        f"SELECT * FROM policy WHERE id = ? AND country_id = ?",
        (policy_id, country_id),
    ).fetchone()

    if row is not None:
        policy = dict(row)
        policy["policy_json"] = json.loads(policy["policy_json"])
    else:
        response_body = dict(
            status="error",
            message=f"Policy #{policy_id} not found.",
        )
        return Response(
            json.dumps(response_body),
            status=404,
            mimetype="application/json",
        )

    country = COUNTRIES.get(country_id)

    try:
        result = country.calculate(
            household["household_json"],
            policy["policy_json"],
            household_id,
            policy_id,
        )

        log_struct(
            event="calculation_success",
            input_data={
                "household_id": household_id,
                "policy_id": policy_id,
            },
            message="Household calculation succeeded.",
            severity="INFO",
        )

    except Exception as e:
        log_struct(
            event="calculation_failed",
            input_data={
                "household_id": household_id,
                "policy_id": policy_id,
            },
            message=f"Calculation failed: {e}",
            severity="ERROR",
        )

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

    try:
        local_database.query(
            f"INSERT INTO computed_household (country_id, household_id, policy_id, computed_household_json, api_version) VALUES (?, ?, ?, ?, ?)",
            (
                country_id,
                household_id,
                policy_id,
                json.dumps(result),
                api_version,
            ),
        )
        log_struct(
            event="computed_household_inserted",
            input_data={
                "household_id": household_id,
                "policy_id": policy_id,
            },
            message="Inserted new computed_household record.",
            severity="INFO",
        )

    except Exception as e:
        log_struct(
            event="computed_household_insert_failed_updating",
            input_data={
                "household_id": household_id,
                "policy_id": policy_id,
            },
            message=f"Insert failed; updated existing record instead. Error: {e}",
            severity="ERROR",
        )

        # Update the result if it already exists
        local_database.query(
            f"UPDATE computed_household SET computed_household_json = ? WHERE country_id = ? AND household_id = ? AND policy_id = ?",
            (json.dumps(result), country_id, household_id, policy_id),
        )

    return dict(
        status="ok",
        message=None,
        result=result,
    )


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

    country = COUNTRIES.get(country_id)

    try:
        result = country.calculate(household_json, policy_json)
        log_struct(
            {
                "event": "calculation_success",
                "input": {
                    "country_id": country_id,
                },
                "message": "Calculation completed successfully.",
            },
            severity="INFO",
        )
    except Exception as e:
        log_struct(
            {
                "event": "calculation_failed",
                "input": {
                    "country_id": country_id,
                },
                "message": f"Error calculating household under policy: {e}",
            },
            severity="ERROR",
        )
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

    return dict(
        status="ok",
        message=None,
        result=result,
    )
