from sqlalchemy.engine.row import Row

from policyengine_api.data import database
from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.services.report_run_service import ReportRunService
from policyengine_api.services.report_spec_service import (
    ECONOMY_REPORT_KINDS,
    ReportSpec,
    ReportSpecService,
)
from policyengine_api.services.run_sync_utils import (
    determine_parent_pointers,
    serialize_json_field,
)


class ReportOutputService:
    def __init__(self):
        self.report_spec_service = ReportSpecService()
        self.report_run_service = ReportRunService()

    def _get_report_output_row(self, report_output_id: int) -> dict | None:
        row: Row | None = database.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _get_simulation_row(self, simulation_id: int) -> dict | None:
        row: Row | None = database.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _get_linked_simulations(self, report_output: dict) -> tuple[dict, dict | None]:
        simulation_1 = self._get_simulation_row(report_output["simulation_1_id"])
        if simulation_1 is None:
            raise ValueError(
                "Report output references missing simulation "
                f"#{report_output['simulation_1_id']}"
            )

        simulation_2 = None
        if report_output["simulation_2_id"] is not None:
            simulation_2 = self._get_simulation_row(report_output["simulation_2_id"])
            if simulation_2 is None:
                raise ValueError(
                    "Report output references missing simulation "
                    f"#{report_output['simulation_2_id']}"
                )

        return simulation_1, simulation_2

    def _get_runs_descending(self, report_output_id: int) -> list[dict]:
        return sorted(
            self.report_run_service.list_report_output_runs(report_output_id),
            key=lambda run: run["run_sequence"],
            reverse=True,
        )

    def _select_mutable_run(
        self, report_output: dict, runs_descending: list[dict]
    ) -> dict | None:
        active_run_id = report_output.get("active_run_id")
        if active_run_id:
            active_run = self.report_run_service.get_report_output_run(active_run_id)
            if active_run is not None:
                return active_run
        return runs_descending[0] if runs_descending else None

    def _derive_report_country_package_version(
        self,
        simulation_1: dict,
        simulation_2: dict | None = None,
    ) -> str | None:
        versions = [
            simulation["api_version"]
            for simulation in (simulation_1, simulation_2)
            if simulation is not None and simulation.get("api_version") is not None
        ]
        if not versions:
            return None
        if len(set(versions)) == 1:
            return versions[0]
        return None

    def _build_version_manifest(
        self,
        report_output: dict,
        report_spec: ReportSpec | None,
        simulation_1: dict | None = None,
        simulation_2: dict | None = None,
    ) -> dict[str, str | None]:
        resolved_dataset = None
        if report_spec is not None and report_spec.report_kind in ECONOMY_REPORT_KINDS:
            resolved_dataset = report_spec.dataset

        return {
            "country_package_version": (
                self._derive_report_country_package_version(simulation_1, simulation_2)
                if simulation_1 is not None
                else None
            ),
            "policyengine_version": None,
            "data_version": None,
            "runtime_app_name": None,
            "report_cache_version": report_output.get("api_version"),
            "simulation_cache_version": None,
            "requested_version_override": None,
            "resolved_dataset": resolved_dataset,
            "resolved_options_hash": None,
        }

    def _get_report_spec_status(self, report_spec: ReportSpec) -> str:
        if report_spec.report_kind in ECONOMY_REPORT_KINDS:
            return "backfilled_assumed"
        return "explicit"

    def _upsert_report_spec(
        self, report_output: dict
    ) -> tuple[ReportSpec | None, dict | None, dict | None]:
        try:
            simulation_1, simulation_2 = self._get_linked_simulations(report_output)
        except ValueError as exc:
            print(
                "Skipping report spec sync for report output "
                f"#{report_output['id']}. Details: {str(exc)}"
            )
            return None, None, None

        try:
            report_spec = self.report_spec_service.build_report_spec(
                report_output=report_output,
                simulation_1=simulation_1,
                simulation_2=simulation_2,
            )
        except ValueError as exc:
            print(
                "Skipping report spec sync for report output "
                f"#{report_output['id']}. Details: {str(exc)}"
            )
            return None, simulation_1, simulation_2

        report_spec_status = self._get_report_spec_status(report_spec)
        existing_spec = None
        try:
            existing_spec = self.report_spec_service.get_report_spec(
                report_output["id"]
            )
        except ValueError:
            existing_spec = None

        if (
            existing_spec is None
            or existing_spec.model_dump() != report_spec.model_dump()
            or report_output.get("report_spec_status") != report_spec_status
        ):
            self.report_spec_service.set_report_spec(
                report_output_id=report_output["id"],
                report_spec=report_spec,
                report_spec_status=report_spec_status,
            )

        return report_spec, simulation_1, simulation_2

    def _run_matches_parent(
        self,
        run: dict,
        report_output: dict,
        report_spec: ReportSpec | None,
        version_manifest: dict[str, str | None],
    ) -> bool:
        expected_snapshot = (
            report_spec.model_dump() if report_spec is not None else None
        )
        return (
            run["status"] == report_output["status"]
            and run.get("output") == report_output.get("output")
            and run.get("error_message") == report_output.get("error_message")
            and run.get("report_spec_snapshot_json") == expected_snapshot
            and run.get("country_package_version")
            == version_manifest["country_package_version"]
            and run.get("policyengine_version")
            == version_manifest["policyengine_version"]
            and run.get("data_version") == version_manifest["data_version"]
            and run.get("runtime_app_name") == version_manifest["runtime_app_name"]
            and run.get("report_cache_version")
            == version_manifest["report_cache_version"]
            and run.get("simulation_cache_version")
            == version_manifest["simulation_cache_version"]
            and run.get("requested_version_override")
            == version_manifest["requested_version_override"]
            and run.get("resolved_dataset") == version_manifest["resolved_dataset"]
            and run.get("resolved_options_hash")
            == version_manifest["resolved_options_hash"]
        )

    def _update_report_run(
        self,
        run_id: str,
        report_output: dict,
        report_spec: ReportSpec | None,
        version_manifest: dict[str, str | None],
    ) -> None:
        report_spec_snapshot = (
            report_spec.model_dump_json() if report_spec is not None else None
        )
        database.query(
            """
            UPDATE report_output_runs
            SET status = ?, output = ?, error_message = ?,
                report_spec_snapshot_json = ?, country_package_version = ?,
                policyengine_version = ?, data_version = ?, runtime_app_name = ?,
                report_cache_version = ?, simulation_cache_version = ?,
                requested_version_override = ?, resolved_dataset = ?,
                resolved_options_hash = ?
            WHERE id = ?
            """,
            (
                report_output["status"],
                serialize_json_field(report_output.get("output")),
                report_output.get("error_message"),
                report_spec_snapshot,
                version_manifest["country_package_version"],
                version_manifest["policyengine_version"],
                version_manifest["data_version"],
                version_manifest["runtime_app_name"],
                version_manifest["report_cache_version"],
                version_manifest["simulation_cache_version"],
                version_manifest["requested_version_override"],
                version_manifest["resolved_dataset"],
                version_manifest["resolved_options_hash"],
                run_id,
            ),
        )

    def _sync_parent_pointers(
        self, report_output: dict, runs_descending: list[dict]
    ) -> None:
        desired_active_run_id, desired_latest_successful_run_id = (
            determine_parent_pointers(report_output["status"], runs_descending)
        )
        if (
            report_output.get("active_run_id") == desired_active_run_id
            and report_output.get("latest_successful_run_id")
            == desired_latest_successful_run_id
        ):
            return

        database.query(
            """
            UPDATE report_outputs
            SET active_run_id = ?, latest_successful_run_id = ?
            WHERE id = ?
            """,
            (
                desired_active_run_id,
                desired_latest_successful_run_id,
                report_output["id"],
            ),
        )

    def ensure_report_output_dual_write_state(self, report_output_id: int) -> dict:
        report_output = self._get_report_output_row(report_output_id)
        if report_output is None:
            raise ValueError(f"Report output #{report_output_id} not found")

        report_spec, simulation_1, simulation_2 = self._upsert_report_spec(
            report_output
        )
        report_output = self._get_report_output_row(report_output_id)
        if report_output is None:
            raise ValueError(f"Report output #{report_output_id} not found after sync")

        version_manifest = self._build_version_manifest(
            report_output,
            report_spec=report_spec,
            simulation_1=simulation_1,
            simulation_2=simulation_2,
        )
        runs_descending = self._get_runs_descending(report_output_id)
        if not runs_descending:
            self.report_run_service.create_report_output_run(
                report_output_id=report_output_id,
                status=report_output["status"],
                trigger_type="initial",
                output=report_output.get("output"),
                error_message=report_output.get("error_message"),
                report_spec_snapshot=(
                    report_spec.model_dump() if report_spec is not None else None
                ),
                version_manifest=version_manifest,
            )
            runs_descending = self._get_runs_descending(report_output_id)
        else:
            mutable_run = self._select_mutable_run(report_output, runs_descending)
            if mutable_run is not None and not self._run_matches_parent(
                mutable_run,
                report_output,
                report_spec,
                version_manifest,
            ):
                self._update_report_run(
                    run_id=mutable_run["id"],
                    report_output=report_output,
                    report_spec=report_spec,
                    version_manifest=version_manifest,
                )
                runs_descending = self._get_runs_descending(report_output_id)

        self._sync_parent_pointers(report_output, runs_descending)
        refreshed_report_output = self._get_report_output_row(report_output_id)
        if refreshed_report_output is None:
            raise ValueError(f"Report output #{report_output_id} not found after sync")
        return refreshed_report_output

    def get_stored_report_output(self, report_output_id: int) -> dict | None:
        """
        Get the raw stored report output row by ID without aliasing to the
        current runtime lineage. This is useful for mutation paths, which must
        update the originally addressed row rather than a resolved alias.
        """
        return self._get_report_output_row(report_output_id)

    def _is_current_report_output(self, report_output: dict) -> bool:
        return report_output.get("api_version") == get_report_output_cache_version(
            report_output["country_id"]
        )

    def _get_or_create_current_report_output(self, report_output: dict) -> dict:
        current_report = self.find_existing_report_output(
            country_id=report_output["country_id"],
            simulation_1_id=report_output["simulation_1_id"],
            simulation_2_id=report_output["simulation_2_id"],
            year=report_output["year"],
        )
        if current_report is not None:
            return current_report

        return self.create_report_output(
            country_id=report_output["country_id"],
            simulation_1_id=report_output["simulation_1_id"],
            simulation_2_id=report_output["simulation_2_id"],
            year=report_output["year"],
        )

    def _alias_report_output(self, report_output_id: int, report_output: dict) -> dict:
        aliased_report = dict(report_output)
        aliased_report["id"] = report_output_id
        return aliased_report

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
                return self.ensure_report_output_dual_write_state(existing_report["id"])

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
            return self.ensure_report_output_dual_write_state(created_report["id"])

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

            report_output = self._get_report_output_row(report_output_id)
            if report_output is None:
                return None

            if self._is_current_report_output(report_output):
                return report_output

            current_report = self._get_or_create_current_report_output(report_output)
            return self._alias_report_output(report_output_id, current_report)

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

        try:
            requested_report = self._get_report_output_row(report_id)
            if requested_report is None:
                raise Exception(f"Report output #{report_id} not found")

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

            if not update_fields:
                print("No fields to update")
                return False

            # Add report_id to the end of values for WHERE clause
            update_values.append(requested_report["id"])

            query = f"UPDATE report_outputs SET {', '.join(update_fields)} WHERE id = ?"

            database.query(query, tuple(update_values))
            self.ensure_report_output_dual_write_state(requested_report["id"])

            print(f"Successfully updated report output #{report_id}")
            return True

        except Exception as e:
            print(f"Error updating report output #{report_id}. Details: {str(e)}")
            raise e
