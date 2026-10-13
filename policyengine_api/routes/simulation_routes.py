"""Flask routes for creating, reading and updating v1 simulation records."""

import json

import jsonschema
import pydantic
from flask import Blueprint, Response, current_app, request
from werkzeug.exceptions import BadRequest, HTTPException, NotFound

from policyengine_api.data.v1_models import Simulation
from policyengine_api.response_factory import _make_error_response
from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.spm import SPMValidationError
from policyengine_api.utils.payload_validators import validate_country

simulation_bp = Blueprint("simulation", __name__)
simulation_service = SimulationService()


def _spm_override_response(payload: dict) -> Response | None:
    if "spm" not in payload:
        return None
    error = SPMValidationError(
        "SPM_SETTINGS_UNSUPPORTED",
        "Simulation records do not accept SPM overrides. Select SPM settings on "
        "the linked household before creating its simulation.",
    )
    return _make_error_response(error, 400, result=None, errors=[error.to_dict()])


def _serialize_v1_simulation(simulation: Simulation) -> dict:
    """Project canonical ORM JSON objects onto the legacy v1 response shape."""
    response = {
        column.name: getattr(simulation, column.name)
        for column in Simulation.__table__.columns
    }
    for field in ("output", "simulation_spec_json"):
        value = response.get(field)
        if value is not None and not isinstance(value, str):
            response[field] = json.dumps(value)

    # This JSON-in-a-string projection exists only for the v1 contract and can
    # go when that contract is retired. v2 response models should expose these
    # fields as native JSON objects rather than carry the historical shape
    # forward.
    return response


def _require_updated_simulation(simulation: Simulation | None) -> Simulation:
    """Return the updated simulation, or raise BadRequest if nothing changed."""
    if simulation is None:
        msg = "No fields to update"
        raise BadRequest(msg)
    return simulation


@simulation_bp.route("/<country_id>/simulation", methods=["POST"])
@validate_country
def create_simulation(country_id: str) -> Response:
    """Create a new simulation record.

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
        msg = "Payload missing from request"
        raise BadRequest(msg)
    if (response := _spm_override_response(payload)) is not None:
        return response

    # Extract required fields
    population_id = payload.get("population_id")
    population_type = payload.get("population_type")
    policy_id = payload.get("policy_id")

    # Validate required fields
    if not population_id:
        msg = "population_id is required"
        raise BadRequest(msg)
    if not population_type:
        msg = "population_type is required"
        raise BadRequest(msg)
    if population_type not in ["household", "geography"]:
        msg = "population_type must be 'household' or 'geography'"
        raise BadRequest(msg)
    if policy_id is None:
        msg = "policy_id is required"
        raise BadRequest(msg)
    if not isinstance(policy_id, int):
        msg = "policy_id must be an integer"
        raise BadRequest(msg)

    try:
        creation = simulation_service.get_or_create_simulation(
            country_id=country_id,
            population_id=population_id,
            population_type=population_type,
            policy_id=policy_id,
        )
        result = _serialize_v1_simulation(creation.simulation)
        message = (
            "Simulation created successfully"
            if creation.created
            else "Simulation already exists"
        )
        status_code = 201 if creation.created else 200

        response_body = dict(
            status="ok",
            message=message,
            result=result,
        )

        return Response(
            json.dumps(response_body),
            status=status_code,
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
        msg = f"Failed to create simulation: {e}"
        raise BadRequest(msg)
    except Exception:
        current_app.logger.exception(
            "Unexpected error creating simulation for country %s", country_id
        )
        raise


@simulation_bp.route("/<country_id>/simulation/<int:simulation_id>", methods=["GET"])
@validate_country
def get_simulation(country_id: str, simulation_id: int) -> Response:
    """Get a simulation record by ID.

    Args:
        country_id (str): The country ID.
        simulation_id (int): The simulation ID.

    """
    print(f"Getting simulation {simulation_id} for country {country_id}")

    if not isinstance(simulation_id, int):
        msg = "simulation_id must be an integer"
        raise BadRequest(msg)
    if simulation_id <= 0:
        msg = "simulation_id must be a positive integer"
        raise BadRequest(msg)

    simulation = simulation_service.get_simulation(country_id, simulation_id)
    result = None if simulation is None else _serialize_v1_simulation(simulation)

    if result is None:
        msg = f"Simulation #{simulation_id} not found."
        raise NotFound(msg)

    response_body = dict(
        status="ok",
        message=None,
        result=result,
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )


@simulation_bp.route("/<country_id>/simulation", methods=["PATCH"])
@validate_country
def update_simulation(country_id: str) -> Response:
    """Update a simulation record with results or error.

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
        msg = "Payload missing from request"
        raise BadRequest(msg)
    if (response := _spm_override_response(payload)) is not None:
        return response

    # Extract optional fields
    status = payload.get("status")
    simulation_id = payload.get("id")
    output = payload.get("output")
    error_message = payload.get("error_message")
    print(f"Updating simulation #{simulation_id} for country {country_id}")

    # Validate status if provided
    if status is not None and status not in ["pending", "complete", "error"]:
        msg = "status must be 'pending', 'complete', or 'error'"
        raise BadRequest(msg)

    # Validate that complete status has output
    if status == "complete" and output is None:
        msg = "output is required when status is 'complete'"
        raise BadRequest(msg)

    try:
        simulation = _require_updated_simulation(
            simulation_service.update_simulation(
                country_id=country_id,
                simulation_id=simulation_id,
                status=status,
                output=output,
                error_message=error_message,
            )
        )

        result = _serialize_v1_simulation(simulation)

        response_body = dict(
            status="ok",
            message="Simulation updated successfully",
            result=result,
        )

        return Response(
            json.dumps(response_body),
            status=200,
            mimetype="application/json",
        )

    except LookupError:
        msg = f"Simulation #{simulation_id} not found."
        raise NotFound(msg) from None
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
        msg = f"Failed to update simulation: {e}"
        raise BadRequest(msg)
    except Exception:
        current_app.logger.exception(
            "Unexpected error updating simulation #%s for country %s",
            simulation_id,
            country_id,
        )
        raise
