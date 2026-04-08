from sqlalchemy.engine.row import Row
import json

from policyengine_api.data import database
from policyengine_api.constants import get_report_output_cache_version


class ReportOutputService:
    def _normalize_stale_congressional_district_output(
        self, report_output: dict
    ) -> dict:
        """
        Strip stale congressional district payloads from legacy US report
        outputs so clients can refresh from the live shared state payload path.
        """
        if report_output.get("country_id") != "us":
            return report_output
        if report_output.get("output") is None:
            return report_output
        if report_output.get("api_version") == get_report_output_cache_version("us"):
            return report_output

        try:
            output = json.loads(report_output["output"])
        except (TypeError, json.JSONDecodeError):
            return report_output

        district_impact = output.get("congressional_district_impact")
        districts = (
            district_impact.get("districts")
            if isinstance(district_impact, dict)
            else None
        )
        if not districts:
            return report_output

        has_complete_outcomes = all(
            isinstance(district.get("winner_percentage"), (int, float))
            and isinstance(district.get("loser_percentage"), (int, float))
            for district in districts
        )
        if has_complete_outcomes:
            return report_output

        normalized_report = dict(report_output)
        output["congressional_district_impact"] = None
        normalized_report["output"] = json.dumps(output)
        return normalized_report

    def find_existing_report_output(
        self,
        country_id: str,
        simulation_1_id: int,
        simulation_2_id: int | None = None,
        year: str = "2025",
    ) -> dict | None:
        """
        Find an existing report output with the same simulation IDs and year.

        Args:
            country_id (str): The country ID.
            simulation_1_id (int): The first simulation ID (required).
            simulation_2_id (int | None): The second simulation ID (optional, for comparisons).
            year (str): The year for the report (defaults to "2025").

        Returns:
            dict | None: The existing report output data or None if not found.
        """
        print("Checking for existing report output")
        api_version = get_report_output_cache_version(country_id)

        try:
            query = "SELECT * FROM report_outputs WHERE country_id = ? AND simulation_1_id = ? AND year = ? AND api_version = ?"
            params = [country_id, simulation_1_id, year, api_version]

            if simulation_2_id is not None:
                query += " AND simulation_2_id = ?"
                params.append(simulation_2_id)
            else:
                query += " AND simulation_2_id IS NULL"

            query += " ORDER BY id DESC"

            row = database.query(query, tuple(params)).fetchone()

            existing_report = None
            if row is not None:
                existing_report = dict(row)
                print(f"Found existing report output with ID: {existing_report['id']}")
                # Keep output as JSON string - frontend expects string format

            return existing_report

        except Exception as e:
            print(f"Error checking for existing report output. Details: {str(e)}")
            raise e

    def create_report_output(
        self,
        country_id: str,
        simulation_1_id: int,
        simulation_2_id: int | None = None,
        year: str = "2025",
    ) -> dict:
        """
        Create a new report output record with pending status.

        Args:
            country_id (str): The country ID.
            simulation_1_id (int): The first simulation ID (required).
            simulation_2_id (int | None): The second simulation ID (optional, for comparisons).
            year (str): The year for the report (defaults to "2025").

        Returns:
            dict: The created report output record.
        """
        print("Creating new report output")
        api_version = get_report_output_cache_version(country_id)

        try:
            existing_report = self.find_existing_report_output(
                country_id, simulation_1_id, simulation_2_id, year
            )
            if existing_report is not None:
                print(
                    f"Reusing existing report output with ID: {existing_report['id']}"
                )
                return existing_report

            # Insert with default status 'pending'
            if simulation_2_id is not None:
                database.query(
                    "INSERT INTO report_outputs (country_id, simulation_1_id, simulation_2_id, api_version, status, year) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        country_id,
                        simulation_1_id,
                        simulation_2_id,
                        api_version,
                        "pending",
                        year,
                    ),
                )
            else:
                database.query(
                    "INSERT INTO report_outputs (country_id, simulation_1_id, api_version, status, year) VALUES (?, ?, ?, ?, ?)",
                    (
                        country_id,
                        simulation_1_id,
                        api_version,
                        "pending",
                        year,
                    ),
                )

            # Safely retrieve the created report output record
            created_report = self.find_existing_report_output(
                country_id, simulation_1_id, simulation_2_id, year
            )

            if created_report is None:
                raise Exception("Failed to retrieve created report output")

            print(f"Created report output with ID: {created_report['id']}")
            return created_report

        except Exception as e:
            print(f"Error creating report output. Details: {str(e)}")
            raise e

    def get_report_output(self, report_output_id: int) -> dict | None:
        """
        Get a report output record by ID.

        Args:
            report_output_id (int): The report output ID.

        Returns:
            dict | None: The report output data or None if not found.
        """
        print(f"Getting report output {report_output_id}")

        try:
            if type(report_output_id) is not int or report_output_id < 0:
                raise Exception(
                    f"Invalid report output ID: {report_output_id}. Must be a positive integer."
                )

            row: Row | None = database.query(
                "SELECT * FROM report_outputs WHERE id = ?",
                (report_output_id,),
            ).fetchone()

            report_output = None
            if row is not None:
                report_output = self._normalize_stale_congressional_district_output(
                    dict(row)
                )
                # Keep output as JSON string - frontend expects string format
                # Frontend will parse it using JSON.parse()

            return report_output

        except Exception as e:
            print(
                f"Error fetching report output #{report_output_id}. Details: {str(e)}"
            )
            raise e

    def update_report_output(
        self,
        country_id: str,
        report_id: int,
        status: str | None = None,
        output: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """
        Update a report output record with results or error.

        Args:
            report_id (int): The report output ID.
            status (str | None): The new status ('complete' or 'error').
            output (str | None): The result output as JSON string (for complete status).
            error_message (str | None): The error message (for error status).

        Returns:
            bool: True if update was successful.
        """
        print(f"Updating report output {report_id}")
        # Automatically update api_version on every update to the latest
        # report-output runtime version token.
        api_version = get_report_output_cache_version(country_id)

        try:
            # Build the update query dynamically based on provided fields
            update_fields = []
            update_values = []

            if status is not None:
                update_fields.append("status = ?")
                update_values.append(status)

            if output is not None:
                update_fields.append("output = ?")
                # Output is already a JSON string from frontend
                update_values.append(output)

            if error_message is not None:
                update_fields.append("error_message = ?")
                update_values.append(error_message)

            # Always update API version
            update_fields.append("api_version = ?")
            update_values.append(api_version)

            if not update_fields:
                print("No fields to update")
                return False

            # Add report_id to the end of values for WHERE clause
            update_values.append(report_id)

            query = f"UPDATE report_outputs SET {', '.join(update_fields)} WHERE id = ?"

            database.query(query, tuple(update_values))

            print(f"Successfully updated report output #{report_id}")
            return True

        except Exception as e:
            print(f"Error updating report output #{report_id}. Details: {str(e)}")
            raise e
