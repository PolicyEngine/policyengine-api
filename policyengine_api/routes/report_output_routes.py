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
REPORT_OUTPUT_RESPONSE_INTERNAL_FIELDS = {
    "active_run_id",
    "latest_successful_run_id",
    "report_identity_hash",
    "report_identity_schema_version",
    "report_spec_json",
    "report_spec_schema_version",
    "report_spec_status",
}
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


def _serialize_report_output_response(report_output: dict) -> dict:
    response_report = dict(report_output)
    for field_name in REPORT_OUTPUT_RESPONSE_INTERNAL_FIELDS:
        response_report.pop(field_name, None)
    return response_report


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
                    ensure_current_report_cache_run=True,
                )
            )
            # Report already exists, return it with 200 status
            response_body = dict(
                status="ok",
                message="Report output already exists",
                result=_serialize_report_output_response(existing_report),
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
            result=_serialize_report_output_response(created_report),
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

    The response result may include requested_at, started_at, and finished_at
    values projected from the selected report_output_runs row. Those fields are
    base report execution metadata, not user-specific user-report association
    last-run metadata.

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
        result=_serialize_report_output_response(report_output),
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )


@report_output_bp.route("/<country_id>/report/<int:report_id>/rerun", methods=["POST"])
@validate_country
def create_report_rerun(country_id: str, report_id: int) -> Response:
    """
    Create a new pending run for an existing report.

    The requested report ID may be a legacy ID; the run is always created under
    the resolved canonical report output.
    """
    payload = request.json or {}
    if not isinstance(payload, dict):
        raise BadRequest("Payload must be an object")

    version_manifest_overrides = _parse_report_run_metadata(payload)

    try:
        if not report_output_service.report_output_exists(country_id, report_id):
            raise NotFound(f"Report #{report_id} not found.")

        rerun = report_output_service.create_report_rerun(
            country_id=country_id,
            report_output_id=report_id,
            version_manifest_overrides=version_manifest_overrides,
        )
    except HTTPException:
        raise
    except ValueError as e:
        current_app.logger.warning(
            "Bad request creating report rerun #%s for country %s: %s",
            report_id,
            country_id,
            e,
        )
        raise BadRequest(f"Failed to create report rerun: {e}") from e

    response_body = dict(
        status="ok",
        message="Report rerun created successfully",
        result=rerun,
    )
    return Response(
        json.dumps(response_body),
        status=201,
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
        - report_output_run_id (str | None): Specific report run to update.
        - status (str): The new status ('pending', 'running', 'complete', or 'error')
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
    report_output_run_id = payload.get("report_output_run_id")
    version_manifest_overrides = _parse_report_run_metadata(payload)
    print(f"Updating report #{report_id} for country {country_id}")

    # Validate status if provided
    if status is not None and status not in [
        "pending",
        "running",
        "complete",
        "error",
    ]:
        raise BadRequest("status must be 'pending', 'running', 'complete', or 'error'")

    # Validate that complete status has output
    if status == "complete" and output is None:
        raise BadRequest("output is required when status is 'complete'")
    if report_output_run_id is not None and not isinstance(report_output_run_id, str):
        raise BadRequest("report_output_run_id must be a string")

    try:
        # First check if the report output exists without running pointer sync:
        # syncing a completed parent before this mutation can clear an active
        # pending rerun that this PATCH is about to mark as running.
        if not report_output_service.report_output_exists(country_id, report_id):
            raise NotFound(f"Report #{report_id} not found.")

        # Update the report output
        success = report_output_service.update_report_output(
            country_id=country_id,
            report_id=report_id,
            status=status,
            output=output,
            error_message=error_message,
            report_output_run_id=report_output_run_id,
            version_manifest_overrides=version_manifest_overrides,
        )

        if not success:
            raise BadRequest("No fields to update")

        if report_output_run_id is not None:
            updated_report = report_output_service.get_report_output_for_run(
                country_id,
                report_id,
                report_output_run_id,
            )
        else:
            updated_report = report_output_service.get_report_output(
                country_id, report_id
            )
        if updated_report is None:
            raise NotFound(f"Report #{report_id} not found.")

        response_body = dict(
            status="ok",
            message="Report output updated successfully",
            result=_serialize_report_output_response(updated_report),
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
