from flask import Blueprint, Response, request
from werkzeug.exceptions import NotFound, BadRequest
import json

from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.constants import CURRENT_YEAR
from policyengine_api.utils.payload_validators import validate_country

report_output_bp = Blueprint("report_output", __name__)
report_output_service = ReportOutputService()
RUN_METADATA_FIELDS = (
    "country_package_version",
    "policyengine_version",
    "data_version",
    "runtime_app_name",
    "resolved_dataset",
)


def _parse_report_run_metadata(payload: dict) -> dict[str, str | None]:
    metadata: dict[str, str | None] = {}
    for field_name in RUN_METADATA_FIELDS:
        if field_name not in payload:
            continue
        value = payload.get(field_name)
        if value is not None and not isinstance(value, str):
            raise BadRequest(f"{field_name} must be a string or null")
        metadata[field_name] = value
    return metadata


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
    report_spec_payload = payload.get("report_spec")
    report_spec_schema_version = payload.get("report_spec_schema_version")

    # Validate required fields
    if simulation_1_id is None:
        raise BadRequest("simulation_1_id is required")
    if not isinstance(simulation_1_id, int):
        raise BadRequest("simulation_1_id must be an integer")
    if simulation_2_id is not None and not isinstance(simulation_2_id, int):
        raise BadRequest("simulation_2_id must be an integer or null")
    if not isinstance(year, str):
        raise BadRequest("year must be a string")
    if report_spec_payload is not None and not isinstance(report_spec_payload, dict):
        raise BadRequest("report_spec must be an object")
    if report_spec_schema_version is not None and not isinstance(
        report_spec_schema_version, int
    ):
        raise BadRequest("report_spec_schema_version must be an integer")

    report_spec = None
    if report_spec_payload is not None:
        try:
            report_spec = report_output_service.parse_report_spec_payload(
                report_spec_payload,
                (
                    report_spec_schema_version
                    if report_spec_schema_version is not None
                    else 1
                ),
            )
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc

    try:
        # Check if report already exists with these simulation IDs and year
        existing_report = report_output_service.find_existing_report_output_for_create(
            country_id=country_id,
            simulation_1_id=simulation_1_id,
            simulation_2_id=simulation_2_id,
            year=year,
            report_spec=report_spec,
        )

        if existing_report:
            existing_report = (
                report_output_service.ensure_report_output_dual_write_state(
                    existing_report["id"],
                    country_id=country_id,
                    explicit_report_spec=report_spec,
                    report_spec_schema_version=report_spec_schema_version,
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
            report_spec=report_spec,
            report_spec_schema_version=report_spec_schema_version,
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

    except Exception as e:
        print(f"Error creating report output: {str(e)}")
        raise BadRequest(f"Failed to create report output: {str(e)}")


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
    version_manifest_overrides = _parse_report_run_metadata(payload)
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
            version_manifest_overrides=version_manifest_overrides,
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

    except NotFound:
        raise
    except Exception as e:
        print(f"Error updating report output: {str(e)}")
        raise BadRequest(f"Failed to update report output: {str(e)}")
