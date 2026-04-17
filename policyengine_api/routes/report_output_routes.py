from flask import Blueprint, Response, current_app, request
from werkzeug.exceptions import HTTPException, NotFound, BadRequest
import json

import jsonschema
import pydantic

from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.constants import CURRENT_YEAR
from policyengine_api.utils.payload_validators import validate_country

report_output_bp = Blueprint("report_output", __name__)
report_output_service = ReportOutputService()


@report_output_bp.route("/<country_id>/report", methods=["POST"])
@validate_country
def create_report_output(country_id: str) -> Response:
    """
    Create a new report output record with pending status.

    Args:
        country_id (str): The country ID.

    Request body should contain:
        - simulation_1_id (int): The first simulation ID (required)
        - simulation_2_id (int | None): The second simulation ID (optional, for comparisons)
        - year (str | None): The year for the report (optional)
    """
    print(f"Creating report output for country {country_id}")
    payload = request.json
    if payload is None:
        raise BadRequest("Payload missing from request")

    # Extract required fields
    simulation_1_id = payload.get("simulation_1_id")
    simulation_2_id = payload.get("simulation_2_id")  # Optional
    year = payload.get("year", CURRENT_YEAR)  # Default to current year as string

    # Validate required fields
    if simulation_1_id is None:
        raise BadRequest("simulation_1_id is required")
    if not isinstance(simulation_1_id, int):
        raise BadRequest("simulation_1_id must be an integer")
    if simulation_2_id is not None and not isinstance(simulation_2_id, int):
        raise BadRequest("simulation_2_id must be an integer or null")
    if not isinstance(year, str):
        raise BadRequest("year must be a string")

    try:
        # Check if report already exists with these simulation IDs and year
        existing_report = report_output_service.find_existing_report_output(
            country_id=country_id,
            simulation_1_id=simulation_1_id,
            simulation_2_id=simulation_2_id,
            year=year,
        )

        if existing_report:
            existing_report = (
                report_output_service.ensure_report_output_dual_write_state(
                    existing_report["id"],
                    country_id=country_id,
                )
            )
            # Report already exists, return it with 200 status
            response_body = dict(
                status="ok",
                message="Report output already exists",
                result=existing_report,
            )

            return Response(
                json.dumps(response_body),
                status=200,
                mimetype="application/json",
            )

        # Create new report output
        created_report = report_output_service.create_report_output(
            country_id=country_id,
            simulation_1_id=simulation_1_id,
            simulation_2_id=simulation_2_id,
            year=year,
        )

        response_body = dict(
            status="ok",
            message="Report output created successfully",
            result=created_report,
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
            "Bad request creating report output for country %s: %s", country_id, e
        )
        raise BadRequest(f"Failed to create report output: {e}")
    except Exception:
        current_app.logger.exception(
            "Unexpected error creating report output for country %s", country_id
        )
        raise


@report_output_bp.route("/<country_id>/report/<int:report_id>", methods=["GET"])
@validate_country
def get_report_output(country_id: str, report_id: int) -> Response:
    """
    Get a report output record by ID.

    Args:
        country_id (str): The country ID.
        report_id (int): The report output ID.
    """
    print(f"Getting report output {report_id} for country {country_id}")

    report_output: dict | None = report_output_service.get_report_output(
        country_id, report_id
    )

    if report_output is None:
        raise NotFound(f"Report #{report_id} not found.")

    response_body = dict(
        status="ok",
        message=None,
        result=report_output,
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )


@report_output_bp.route("/<country_id>/report", methods=["PATCH"])
@validate_country
def update_report_output(country_id: str) -> Response:
    """
    Update a report output record with results or error.

    Args:
        country_id (str): The country ID.

    Request body can contain:
        - id (int): The report output ID.
        - status (str): The new status ('complete' or 'error')
        - output (dict): The result output (for complete status)
        - api_version (str): The API version of the report
        - error_message (str): The error message (for error status)
    """

    payload = request.json
    if payload is None:
        raise BadRequest("Payload missing from request")

    # Extract optional fields
    status = payload.get("status")
    report_id = payload.get("id")
    output = payload.get("output")
    error_message = payload.get("error_message")
    print(f"Updating report #{report_id} for country {country_id}")

    # Validate status if provided
    if status is not None and status not in ["pending", "complete", "error"]:
        raise BadRequest("status must be 'pending', 'complete', or 'error'")

    # Validate that complete status has output
    if status == "complete" and output is None:
        raise BadRequest("output is required when status is 'complete'")

    try:
        # First check if the report output exists
        existing_report = report_output_service.get_stored_report_output(
            country_id, report_id
        )
        if existing_report is None:
            raise NotFound(f"Report #{report_id} not found.")

        # Update the report output
        success = report_output_service.update_report_output(
            country_id=country_id,
            report_id=report_id,
            status=status,
            output=output,
            error_message=error_message,
        )

        if not success:
            raise BadRequest("No fields to update")

        # Get the updated stored record so stale-runtime jobs do not appear to
        # complete the current runtime lineage in the PATCH response.
        updated_report = report_output_service.get_stored_report_output(
            country_id, report_id
        )

        response_body = dict(
            status="ok",
            message="Report output updated successfully",
            result=updated_report,
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
            "Bad request updating report #%s for country %s: %s",
            report_id,
            country_id,
            e,
        )
        raise BadRequest(f"Failed to update report output: {e}")
    except Exception:
        current_app.logger.exception(
            "Unexpected error updating report #%s for country %s",
            report_id,
            country_id,
        )
        raise
