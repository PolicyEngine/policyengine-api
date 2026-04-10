from flask import Blueprint, Response, request
from werkzeug.exceptions import NotFound, BadRequest
import json

from policyengine_api.constants import (
    CURRENT_YEAR,
    get_economy_impact_cache_version,
)
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.utils.payload_validators import validate_country

report_output_bp = Blueprint("report_output", __name__)
report_output_service = ReportOutputService()
simulation_service = SimulationService()
reform_impacts_service = ReformImpactsService()


def _get_linked_simulation_or_raise(country_id: str, simulation_id: int) -> dict:
    simulation = simulation_service.get_simulation(country_id, simulation_id)
    if simulation is None:
        raise BadRequest(
            f"Report references simulation #{simulation_id}, but it could not be found for country {country_id}."
        )
    return simulation


def _load_report_and_linked_simulations(
    country_id: str, report_id: int
) -> tuple[dict, dict, dict | None]:
    report_output = report_output_service.get_stored_report_output(report_id)
    if report_output is None or report_output["country_id"] != country_id:
        raise NotFound(f"Report #{report_id} not found.")

    simulation_1 = _get_linked_simulation_or_raise(
        country_id=country_id,
        simulation_id=report_output["simulation_1_id"],
    )

    simulation_2 = None
    if report_output["simulation_2_id"] is not None:
        simulation_2 = _get_linked_simulation_or_raise(
            country_id=country_id,
            simulation_id=report_output["simulation_2_id"],
        )

    if (
        simulation_2 is not None
        and simulation_1["population_type"] != simulation_2["population_type"]
    ):
        raise BadRequest(
            f"Report #{report_id} links simulations with mismatched population types."
        )

    return report_output, simulation_1, simulation_2


def _reset_linked_simulations(country_id: str, *simulations: dict | None) -> list[int]:
    reset_simulation_ids: list[int] = []
    seen_ids: set[int] = set()

    for simulation in simulations:
        if simulation is None or simulation["id"] in seen_ids:
            continue
        simulation_service.reset_simulation(country_id, simulation["id"])
        seen_ids.add(simulation["id"])
        reset_simulation_ids.append(simulation["id"])

    return reset_simulation_ids


def _delete_economy_cache_for_legacy_report_path(
    country_id: str,
    report_output: dict,
    simulation_1: dict,
    simulation_2: dict | None,
) -> int | None:
    """
    Delete reform_impact rows using the current legacy app path assumptions:
    dataset is always "default", options_hash is always "[]", and the report
    year maps directly to the economy time period. This is correct for the
    current app-generated legacy report flow, not arbitrary historical callers.
    """
    return reform_impacts_service.delete_reform_impacts(
        country_id=country_id,
        policy_id=(
            simulation_2["policy_id"]
            if simulation_2 is not None
            else simulation_1["policy_id"]
        ),
        baseline_policy_id=simulation_1["policy_id"],
        region=simulation_1["population_id"],
        dataset="default",
        time_period=report_output["year"],
        options_hash="[]",
        api_version=get_economy_impact_cache_version(country_id),
    )


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

    report_output: dict | None = report_output_service.get_report_output(report_id)

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
        existing_report = report_output_service.get_stored_report_output(report_id)
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
        updated_report = report_output_service.get_stored_report_output(report_id)

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


@report_output_bp.route("/<country_id>/report/<int:report_id>/rerun", methods=["POST"])
@validate_country
def rerun_report_output(country_id: str, report_id: int) -> Response:
    """
    Reset a legacy report output so the current app can recompute it.

    For economy reports this also purges reform_impact rows using the current
    app-path assumptions about dataset/options provenance.
    """
    print(f"Rerunning report output {report_id} for country {country_id}")

    report_output, simulation_1, simulation_2 = _load_report_and_linked_simulations(
        country_id=country_id,
        report_id=report_id,
    )

    report_output_service.reset_report_output(country_id, report_id)
    reset_simulation_ids = _reset_linked_simulations(
        country_id, simulation_1, simulation_2
    )

    economy_cache_rows_deleted = 0
    if simulation_1["population_type"] == "geography":
        deleted_rows = _delete_economy_cache_for_legacy_report_path(
            country_id=country_id,
            report_output=report_output,
            simulation_1=simulation_1,
            simulation_2=simulation_2,
        )
        economy_cache_rows_deleted = deleted_rows or 0

    response_body = dict(
        status="ok",
        message="Report rerun reset successfully",
        result=dict(
            report_id=report_id,
            report_type=simulation_1["population_type"],
            simulation_ids=reset_simulation_ids,
            economy_cache_rows_deleted=economy_cache_rows_deleted,
        ),
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )
