from flask import Blueprint, Response, current_app, request
from werkzeug.exceptions import HTTPException, NotFound, BadRequest
import json

import jsonschema
import pydantic

from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.utils.payload_validators import validate_country

simulation_bp = Blueprint("simulation", __name__)
simulation_service = SimulationService()


@simulation_bp.route("/<country_id>/simulation", methods=["POST"])
@validate_country
def create_simulation(country_id: str) -> Response:
    """
    Create a new simulation record.

    Args:
        country_id (str): The country ID.

    Request body should contain:
        - population_id (str): The population identifier (household or geography ID)
        - population_type (str): Type of population ('household' or 'geography')
        - policy_id (int): The policy ID
    """
    print(f"Creating simulation for country {country_id}")

    payload = request.json
    if payload is None:
        raise BadRequest("Payload missing from request")

    # Extract required fields
    population_id = payload.get("population_id")
    population_type = payload.get("population_type")
    policy_id = payload.get("policy_id")

    # Validate required fields
    if not population_id:
        raise BadRequest("population_id is required")
    if not population_type:
        raise BadRequest("population_type is required")
    if population_type not in ["household", "geography"]:
        raise BadRequest("population_type must be 'household' or 'geography'")
    if policy_id is None:
        raise BadRequest("policy_id is required")
    if not isinstance(policy_id, int):
        raise BadRequest("policy_id must be an integer")

    try:
        # Check if simulation already exists with these parameters
        existing_simulation = simulation_service.find_existing_simulation(
            country_id=country_id,
            population_id=population_id,
            population_type=population_type,
            policy_id=policy_id,
        )

        if existing_simulation:
            existing_simulation = simulation_service.ensure_simulation_dual_write_state(
                existing_simulation["id"],
                country_id=country_id,
            )
            # Simulation already exists, return it with 200 status
            response_body = dict(
                status="ok",
                message="Simulation already exists",
                result=existing_simulation,
            )

            return Response(
                json.dumps(response_body),
                status=200,
                mimetype="application/json",
            )

        # Create new simulation
        created_simulation = simulation_service.create_simulation(
            country_id=country_id,
            population_id=population_id,
            population_type=population_type,
            policy_id=policy_id,
        )

        response_body = dict(
            status="ok",
            message="Simulation created successfully",
            result=created_simulation,
        )

        return Response(
            json.dumps(response_body),
            status=201,
            mimetype="application/json",
        )

    except HTTPException:
        # Let explicit client-error responses (BadRequest/NotFound/etc.) pass
        # through without being logged as "Unexpected error".
        raise
    except (ValueError, pydantic.ValidationError, jsonschema.ValidationError) as e:
        current_app.logger.warning(
            "Bad request creating simulation for country %s: %s", country_id, e
        )
        raise BadRequest(f"Failed to create simulation: {e}")
    except Exception:
        current_app.logger.exception(
            "Unexpected error creating simulation for country %s", country_id
        )
        raise


@simulation_bp.route("/<country_id>/simulation/<int:simulation_id>", methods=["GET"])
@validate_country
def get_simulation(country_id: str, simulation_id: int) -> Response:
    """
    Get a simulation record by ID.

    Args:
        country_id (str): The country ID.
        simulation_id (int): The simulation ID.
    """
    print(f"Getting simulation {simulation_id} for country {country_id}")

    if not isinstance(simulation_id, int):
        raise BadRequest("simulation_id must be an integer")
    if simulation_id <= 0:
        raise BadRequest("simulation_id must be a positive integer")

    simulation: dict | None = simulation_service.get_simulation(
        country_id, simulation_id
    )

    if simulation is None:
        raise NotFound(f"Simulation #{simulation_id} not found.")

    response_body = dict(
        status="ok",
        message=None,
        result=simulation,
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )


@simulation_bp.route("/<country_id>/simulation", methods=["PATCH"])
@validate_country
def update_simulation(country_id: str) -> Response:
    """
    Update a simulation record with results or error.

    Args:
        country_id (str): The country ID.

    Request body can contain:
        - id (int): The simulation ID.
        - status (str): The new status ('complete' or 'error')
        - output (dict): The result output (for complete status)
        - api_version (str): The API version of the simulation
        - error_message (str): The error message (for error status)
    """

    payload = request.json
    if payload is None:
        raise BadRequest("Payload missing from request")

    # Extract optional fields
    status = payload.get("status")
    simulation_id = payload.get("id")
    output = payload.get("output")
    error_message = payload.get("error_message")
    print(f"Updating simulation #{simulation_id} for country {country_id}")

    # Validate status if provided
    if status is not None and status not in ["pending", "complete", "error"]:
        raise BadRequest("status must be 'pending', 'complete', or 'error'")

    # Validate that complete status has output
    if status == "complete" and output is None:
        raise BadRequest("output is required when status is 'complete'")

    try:
        # First check if the simulation exists
        existing_simulation = simulation_service.get_simulation(
            country_id, simulation_id
        )
        if existing_simulation is None:
            raise NotFound(f"Simulation #{simulation_id} not found.")

        # Update the simulation
        success = simulation_service.update_simulation(
            country_id=country_id,
            simulation_id=simulation_id,
            status=status,
            output=output,
            error_message=error_message,
        )

        if not success:
            raise BadRequest("No fields to update")

        # Get the updated record
        updated_simulation = simulation_service.get_simulation(
            country_id, simulation_id
        )

        response_body = dict(
            status="ok",
            message="Simulation updated successfully",
            result=updated_simulation,
        )

        return Response(
            json.dumps(response_body),
            status=200,
            mimetype="application/json",
        )

    except HTTPException:
        # Let explicit client-error responses (BadRequest/NotFound/etc.) pass
        # through without being logged as "Unexpected error".
        raise
    except (ValueError, pydantic.ValidationError, jsonschema.ValidationError) as e:
        current_app.logger.warning(
            "Bad request updating simulation #%s for country %s: %s",
            simulation_id,
            country_id,
            e,
        )
        raise BadRequest(f"Failed to update simulation: {e}")
    except Exception:
        current_app.logger.exception(
            "Unexpected error updating simulation #%s for country %s",
            simulation_id,
            country_id,
        )
        raise
