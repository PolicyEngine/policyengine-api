import json
from datetime import datetime
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.data import database
from policyengine_api.utils.database_utils import get_inserted_record_id, find_existing_record


class ReportOutputService:

    def find_existing_report_output(
        self,
        simulation_1_id: int,
        simulation_2_id: int | None = None,
    ) -> dict | None:
        """
        Find an existing report output with the same simulation IDs.

        Args:
            simulation_1_id (int): The first simulation ID (required).
            simulation_2_id (int | None): The second simulation ID (optional, for comparisons).

        Returns:
            dict | None: The existing report output data or None if not found.
        """
        print("Checking for existing report output")

        try:
            existing_report = find_existing_record(
                database,
                "report_outputs",
                {
                    "simulation_1_id": simulation_1_id,
                    "simulation_2_id": simulation_2_id,
                }
            )
            
            if existing_report:
                print(f"Found existing report output with ID: {existing_report['id']}")
                # Parse JSON output if present
                if existing_report.get("output"):
                    existing_report["output"] = json.loads(existing_report["output"])
            
            return existing_report

        except Exception as e:
            print(f"Error checking for existing report output. Details: {str(e)}")
            raise e

    def create_report_output(
        self,
        simulation_1_id: int,
        simulation_2_id: int | None = None,
    ) -> int:
        """
        Create a new report output record with pending status.

        Args:
            simulation_1_id (int): The first simulation ID (required).
            simulation_2_id (int | None): The second simulation ID (optional, for comparisons).

        Returns:
            int: The ID of the created report output.
        """
        print("Creating new report output")

        try:
            # Insert with default status 'pending'
            if simulation_2_id is not None:
                database.query(
                    "INSERT INTO report_outputs (simulation_1_id, simulation_2_id, status) VALUES (?, ?, ?)",
                    (simulation_1_id, simulation_2_id, "pending"),
                )
            else:
                database.query(
                    "INSERT INTO report_outputs (simulation_1_id, status) VALUES (?, ?)",
                    (simulation_1_id, "pending"),
                )

            # Safely retrieve the ID of the created report output
            report_output_id = get_inserted_record_id(
                database,
                "report_outputs",
                {
                    "simulation_1_id": simulation_1_id,
                    "simulation_2_id": simulation_2_id,
                    "status": "pending",
                }
            )

            print(f"Created report output with ID: {report_output_id}")
            return report_output_id

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

            row: LegacyRow | None = database.query(
                "SELECT * FROM report_outputs WHERE id = ?",
                (report_output_id,),
            ).fetchone()

            report_output = None
            if row is not None:
                report_output = dict(row)
                # Parse JSON output if present
                if report_output.get("output"):
                    report_output["output"] = json.loads(
                        report_output["output"]
                    )

            return report_output

        except Exception as e:
            print(
                f"Error fetching report output #{report_output_id}. Details: {str(e)}"
            )
            raise e

    def update_report_output(
        self,
        report_output_id: int,
        status: str | None = None,
        output: dict | None = None,
        error_message: str | None = None,
    ) -> bool:
        """
        Update a report output record with results or error.

        Args:
            report_output_id (int): The report output ID.
            status (str | None): The new status ('complete' or 'error').
            output (dict | None): The result output (for complete status).
            error_message (str | None): The error message (for error status).

        Returns:
            bool: True if update was successful.
        """
        print(f"Updating report output {report_output_id}")

        try:
            # Build the update query dynamically based on provided fields
            update_fields = []
            update_values = []

            if status is not None:
                update_fields.append("status = ?")
                update_values.append(status)

            if output is not None:
                update_fields.append("output = ?")
                update_values.append(json.dumps(output))

            if error_message is not None:
                update_fields.append("error_message = ?")
                update_values.append(error_message)

            # Always update the updated_at timestamp when any field is modified
            if update_fields:
                update_fields.append("updated_at = CURRENT_TIMESTAMP")

            if not update_fields:
                print("No fields to update")
                return False

            # Add report_output_id to the end of values for WHERE clause
            update_values.append(report_output_id)

            query = f"UPDATE report_outputs SET {', '.join(update_fields)} WHERE id = ?"

            database.query(query, tuple(update_values))

            print(f"Successfully updated report output #{report_output_id}")
            return True

        except Exception as e:
            print(
                f"Error updating report output #{report_output_id}. Details: {str(e)}"
            )
            raise e
