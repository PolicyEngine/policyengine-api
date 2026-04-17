import uuid

from sqlalchemy.engine.row import Row

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.data import database
from policyengine_api.services.report_spec_service import (
    ECONOMY_REPORT_KINDS,
    ReportSpec,
    REPORT_SPEC_SCHEMA_VERSION,
    ReportSpecService,
)
from policyengine_api.services.run_sync_utils import (
    determine_parent_pointers,
    parse_json_field,
    serialize_json_field,
)
from policyengine_api.services.simulation_service import SimulationService


class ReportOutputService:
    def __init__(self):
        self.report_spec_service = ReportSpecService()
        self.simulation_service = SimulationService()

    def _lock_clause(self) -> str:
        return "" if database.local else " FOR UPDATE"

    def _get_report_output_row(
        self,
        report_output_id: int,
        *,
        queryer=None,
        country_id: str | None = None,
        for_update: bool = False,
    ) -> dict | None:
        queryer = queryer or database
        query = "SELECT * FROM report_outputs WHERE id = ?"
        params: list[int | str] = [report_output_id]
        if country_id is not None:
            query += " AND country_id = ?"
            params.append(country_id)
        if for_update:
            query += self._lock_clause()

        row: Row | None = queryer.query(query, tuple(params)).fetchone()
        return dict(row) if row is not None else None

    def _get_linked_simulations(
        self,
        report_output: dict,
        *,
        queryer=None,
        bootstrap_dual_write_state: bool = False,
    ) -> tuple[dict, dict | None]:
        queryer = queryer or database
        if bootstrap_dual_write_state:
            simulation_1 = self.simulation_service._ensure_simulation_dual_write_state_in_transaction(
                queryer,
                report_output["simulation_1_id"],
                country_id=report_output["country_id"],
            )
        else:
            simulation_1 = self.simulation_service._get_simulation_row(
                report_output["simulation_1_id"],
                queryer=queryer,
                country_id=report_output["country_id"],
            )
        if simulation_1 is None:
            raise ValueError(
                "Report output references missing simulation "
                f"#{report_output['simulation_1_id']}"
            )

        simulation_2 = None
        if report_output["simulation_2_id"] is not None:
            if bootstrap_dual_write_state:
                simulation_2 = self.simulation_service._ensure_simulation_dual_write_state_in_transaction(
                    queryer,
                    report_output["simulation_2_id"],
                    country_id=report_output["country_id"],
                )
            else:
                simulation_2 = self.simulation_service._get_simulation_row(
                    report_output["simulation_2_id"],
                    queryer=queryer,
                    country_id=report_output["country_id"],
                )
            if simulation_2 is None:
                raise ValueError(
                    "Report output references missing simulation "
                    f"#{report_output['simulation_2_id']}"
                )

        return simulation_1, simulation_2

    def _require_simulation_exists(
        self,
        tx,
        *,
        country_id: str,
        simulation_id: int,
    ) -> dict:
        simulation = self.simulation_service._get_simulation_row(
            simulation_id,
            queryer=tx,
            country_id=country_id,
        )
        if simulation is None:
            raise ValueError(
                f"Report output references missing simulation #{simulation_id}"
            )
        return simulation

    def _list_report_runs_descending(
        self, report_output_id: int, *, queryer=None
    ) -> list[dict]:
        queryer = queryer or database
        rows = queryer.query(
            """
            SELECT * FROM report_output_runs
            WHERE report_output_id = ?
            ORDER BY run_sequence DESC
            """,
            (report_output_id,),
        ).fetchall()

        runs = []
        for row in rows:
            run = dict(row)
            run["report_spec_snapshot_json"] = parse_json_field(
                run.get("report_spec_snapshot_json")
            )
            runs.append(run)
        return runs

    def _select_mutable_run(
        self, report_output: dict, runs_descending: list[dict]
    ) -> dict | None:
        active_run_id = report_output.get("active_run_id")
        if active_run_id is not None:
            for run in runs_descending:
                if run["id"] == active_run_id:
                    return run
        return runs_descending[0] if runs_descending else None

    def _derive_report_country_package_version(
        self,
        simulation_1: dict | None,
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
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> dict[str, str | None]:
        resolved_dataset = None
        if report_spec is not None and report_spec.report_kind in ECONOMY_REPORT_KINDS:
            resolved_dataset = report_spec.dataset

        version_manifest = {
            "country_package_version": self._derive_report_country_package_version(
                simulation_1, simulation_2
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
        for key, value in (version_manifest_overrides or {}).items():
            if key in version_manifest and value is not None:
                version_manifest[key] = value
        return version_manifest

    def _get_report_spec_status(self, report_spec: ReportSpec) -> str:
        if report_spec.report_kind in ECONOMY_REPORT_KINDS:
            return "backfilled_assumed"
        return "explicit"

    def _persist_explicit_report_spec_in_transaction(
        self,
        tx,
        report_output: dict,
        simulation_1: dict,
        simulation_2: dict | None,
        explicit_report_spec: ReportSpec,
        report_spec_schema_version: int | None = None,
    ) -> ReportSpec:
        schema_version = (
            report_spec_schema_version
            if report_spec_schema_version is not None
            else REPORT_SPEC_SCHEMA_VERSION
        )
        self.report_spec_service._validate_schema_version(schema_version)
        self.report_spec_service.validate_report_spec_matches_context(
            report_output,
            explicit_report_spec,
            simulation_1,
            simulation_2,
        )
        report_spec_status = "explicit"
        existing_spec = parse_json_field(report_output.get("report_spec_json"))
        if (
            existing_spec != explicit_report_spec.model_dump()
            or report_output.get("report_kind") != explicit_report_spec.report_kind
            or report_output.get("report_spec_schema_version") != schema_version
            or report_output.get("report_spec_status") != report_spec_status
        ):
            tx.query(
                """
                UPDATE report_outputs
                SET report_kind = ?, report_spec_json = ?,
                    report_spec_schema_version = ?, report_spec_status = ?
                WHERE id = ?
                """,
                (
                    explicit_report_spec.report_kind,
                    explicit_report_spec.model_dump_json(),
                    schema_version,
                    report_spec_status,
                    report_output["id"],
                ),
            )
            report_output["report_kind"] = explicit_report_spec.report_kind
            report_output["report_spec_json"] = explicit_report_spec.model_dump()
            report_output["report_spec_schema_version"] = schema_version
            report_output["report_spec_status"] = report_spec_status
        return explicit_report_spec

    def _load_existing_explicit_report_spec(
        self,
        report_output: dict,
        simulation_1: dict,
        simulation_2: dict | None,
    ) -> ReportSpec | None:
        if report_output.get("report_spec_status") != "explicit":
            return None

        raw_spec = parse_json_field(report_output.get("report_spec_json"))
        if raw_spec is None:
            raise ValueError(
                "Stored explicit report spec is missing report_spec_json"
            )

        report_spec = self.report_spec_service.parse_report_spec(
            raw_spec,
            schema_version=report_output.get("report_spec_schema_version"),
        )
        if report_output.get("report_kind") != report_spec.report_kind:
            raise ValueError(
                "Stored explicit report kind must match stored report spec"
            )
        self.report_spec_service.validate_report_spec_matches_context(
            report_output,
            report_spec,
            simulation_1,
            simulation_2,
        )
        return report_spec

    def _derive_and_upsert_report_spec_in_transaction(
        self,
        tx,
        report_output: dict,
        simulation_1: dict,
        simulation_2: dict | None,
    ) -> ReportSpec | None:
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
            return None

        report_spec_status = self._get_report_spec_status(report_spec)
        existing_spec = parse_json_field(report_output.get("report_spec_json"))
        if (
            existing_spec != report_spec.model_dump()
            or report_output.get("report_kind") != report_spec.report_kind
            or report_output.get("report_spec_schema_version") != 1
            or report_output.get("report_spec_status") != report_spec_status
        ):
            tx.query(
                """
                UPDATE report_outputs
                SET report_kind = ?, report_spec_json = ?,
                    report_spec_schema_version = ?, report_spec_status = ?
                WHERE id = ?
                """,
                (
                    report_spec.report_kind,
                    report_spec.model_dump_json(),
                    1,
                    report_spec_status,
                    report_output["id"],
                ),
            )
            report_output["report_kind"] = report_spec.report_kind
            report_output["report_spec_json"] = report_spec.model_dump()
            report_output["report_spec_schema_version"] = 1
            report_output["report_spec_status"] = report_spec_status

        return report_spec

    def _upsert_report_spec_in_transaction(
        self,
        tx,
        report_output: dict,
        simulation_1: dict | None,
        simulation_2: dict | None,
        explicit_report_spec: ReportSpec | None = None,
        report_spec_schema_version: int | None = None,
    ) -> ReportSpec | None:
        if simulation_1 is None:
            if explicit_report_spec is not None:
                raise ValueError(
                    "Explicit report specs require linked simulations to be present"
                )
            if report_output.get("report_spec_status") == "explicit":
                raise ValueError(
                    "Stored explicit report specs require linked simulations to be present"
                )
            return None

        if explicit_report_spec is not None:
            return self._persist_explicit_report_spec_in_transaction(
                tx,
                report_output,
                simulation_1,
                simulation_2,
                explicit_report_spec,
                report_spec_schema_version=report_spec_schema_version,
            )

        stored_explicit_report_spec = self._load_existing_explicit_report_spec(
            report_output,
            simulation_1,
            simulation_2,
        )
        if stored_explicit_report_spec is not None:
            return stored_explicit_report_spec

        return self._derive_and_upsert_report_spec_in_transaction(
            tx,
            report_output,
            simulation_1,
            simulation_2,
        )

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

    def _insert_bootstrap_report_run(
        self,
        tx,
        report_output: dict,
        report_spec: ReportSpec | None,
        version_manifest: dict[str, str | None],
    ) -> None:
        tx.query(
            """
            INSERT INTO report_output_runs (
                id, report_output_id, run_sequence, status, output, error_message,
                trigger_type, requested_at, started_at, finished_at, source_run_id,
                report_spec_snapshot_json, country_package_version, policyengine_version,
                data_version, runtime_app_name, report_cache_version,
                simulation_cache_version, requested_version_override, resolved_dataset,
                resolved_options_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                report_output["id"],
                1,
                report_output["status"],
                serialize_json_field(report_output.get("output")),
                report_output.get("error_message"),
                "initial",
                None,
                None,
                None,
                None,
                (report_spec.model_dump_json() if report_spec is not None else None),
                version_manifest["country_package_version"],
                version_manifest["policyengine_version"],
                version_manifest["data_version"],
                version_manifest["runtime_app_name"],
                version_manifest["report_cache_version"],
                version_manifest["simulation_cache_version"],
                version_manifest["requested_version_override"],
                version_manifest["resolved_dataset"],
                version_manifest["resolved_options_hash"],
            ),
        )

    def _update_report_run_in_transaction(
        self,
        tx,
        run_id: str,
        report_output: dict,
        report_spec: ReportSpec | None,
        version_manifest: dict[str, str | None],
    ) -> None:
        tx.query(
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
                (report_spec.model_dump_json() if report_spec is not None else None),
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

    def _sync_parent_pointers_in_transaction(
        self,
        tx,
        report_output: dict,
        runs_descending: list[dict],
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

        tx.query(
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
        report_output["active_run_id"] = desired_active_run_id
        report_output["latest_successful_run_id"] = desired_latest_successful_run_id

    def _ensure_report_output_dual_write_state_in_transaction(
        self,
        tx,
        report_output_id: int,
        *,
        country_id: str | None = None,
        explicit_report_spec: ReportSpec | None = None,
        report_spec_schema_version: int | None = None,
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> dict:
        report_output = self._get_report_output_row(
            report_output_id,
            queryer=tx,
            country_id=country_id,
            for_update=True,
        )
        if report_output is None:
            raise ValueError(f"Report output #{report_output_id} not found")

        try:
            simulation_1, simulation_2 = self._get_linked_simulations(
                report_output,
                queryer=tx,
                bootstrap_dual_write_state=True,
            )
        except ValueError as exc:
            if explicit_report_spec is not None:
                raise
            print(
                "Skipping linked simulation sync for report output "
                f"#{report_output_id}. Details: {str(exc)}"
            )
            simulation_1, simulation_2 = None, None

        report_spec = self._upsert_report_spec_in_transaction(
            tx,
            report_output,
            simulation_1,
            simulation_2,
            explicit_report_spec=explicit_report_spec,
            report_spec_schema_version=report_spec_schema_version,
        )
        version_manifest = self._build_version_manifest(
            report_output,
            report_spec=report_spec,
            simulation_1=simulation_1,
            simulation_2=simulation_2,
            version_manifest_overrides=version_manifest_overrides,
        )
        runs_descending = self._list_report_runs_descending(
            report_output_id, queryer=tx
        )
        if not runs_descending:
            self._insert_bootstrap_report_run(
                tx,
                report_output,
                report_spec,
                version_manifest,
            )
            runs_descending = self._list_report_runs_descending(
                report_output_id, queryer=tx
            )
        else:
            mutable_run = self._select_mutable_run(report_output, runs_descending)
            if mutable_run is not None and not self._run_matches_parent(
                mutable_run,
                report_output,
                report_spec,
                version_manifest,
            ):
                self._update_report_run_in_transaction(
                    tx,
                    run_id=mutable_run["id"],
                    report_output=report_output,
                    report_spec=report_spec,
                    version_manifest=version_manifest,
                )
                runs_descending = self._list_report_runs_descending(
                    report_output_id, queryer=tx
                )

        self._sync_parent_pointers_in_transaction(tx, report_output, runs_descending)
        refreshed_report_output = self._get_report_output_row(
            report_output_id,
            queryer=tx,
            country_id=country_id,
        )
        if refreshed_report_output is None:
            raise ValueError(f"Report output #{report_output_id} not found after sync")
        return refreshed_report_output

    def ensure_report_output_dual_write_state(
        self,
        report_output_id: int,
        country_id: str | None = None,
        explicit_report_spec: ReportSpec | None = None,
        report_spec_schema_version: int | None = None,
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> dict:
        return database.transaction(
            lambda tx: self._ensure_report_output_dual_write_state_in_transaction(
                tx,
                report_output_id,
                country_id=country_id,
                explicit_report_spec=explicit_report_spec,
                report_spec_schema_version=report_spec_schema_version,
                version_manifest_overrides=version_manifest_overrides,
            )
        )

    def parse_report_spec_payload(
        self,
        raw_report_spec: dict,
        schema_version: int = REPORT_SPEC_SCHEMA_VERSION,
    ) -> ReportSpec:
        return self.report_spec_service.parse_report_spec(
            raw_report_spec,
            schema_version=schema_version,
        )

    def get_stored_report_output(
        self, country_id: str, report_output_id: int
    ) -> dict | None:
        """
        Get the raw stored report output row by ID without aliasing to the
        current runtime lineage. This is useful for mutation paths, which must
        update the originally addressed row rather than a resolved alias.
        """
        return self._get_report_output_row(report_output_id, country_id=country_id)

    def _is_current_report_output(self, report_output: dict) -> bool:
        return report_output.get("api_version") == get_report_output_cache_version(
            report_output["country_id"]
        )

    def _find_existing_report_output_row(
        self,
        *,
        country_id: str,
        simulation_1_id: int,
        simulation_2_id: int | None,
        year: str,
        queryer=None,
    ) -> dict | None:
        queryer = queryer or database
        api_version = get_report_output_cache_version(country_id)
        query = """
            SELECT * FROM report_outputs
            WHERE country_id = ? AND simulation_1_id = ? AND year = ? AND api_version = ?
        """
        params: list[int | str] = [country_id, simulation_1_id, year, api_version]
        if simulation_2_id is not None:
            query += " AND simulation_2_id = ?"
            params.append(simulation_2_id)
        else:
            query += " AND simulation_2_id IS NULL"
        query += " ORDER BY id DESC"

        row = queryer.query(query, tuple(params)).fetchone()
        return dict(row) if row is not None else None

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
        """
        print("Checking for existing report output")

        try:
            existing_report = self._find_existing_report_output_row(
                country_id=country_id,
                simulation_1_id=simulation_1_id,
                simulation_2_id=simulation_2_id,
                year=year,
            )
            if existing_report is not None:
                print(f"Found existing report output with ID: {existing_report['id']}")
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
        report_spec: ReportSpec | None = None,
        report_spec_schema_version: int | None = None,
    ) -> dict:
        """
        Create a new report output record with pending status.
        """
        print("Creating new report output")
        api_version = get_report_output_cache_version(country_id)

        try:

            def tx_callback(tx):
                existing_report = self._find_existing_report_output_row(
                    country_id=country_id,
                    simulation_1_id=simulation_1_id,
                    simulation_2_id=simulation_2_id,
                    year=year,
                    queryer=tx,
                )
                if existing_report is not None:
                    print(
                        f"Reusing existing report output with ID: {existing_report['id']}"
                    )
                    return self._ensure_report_output_dual_write_state_in_transaction(
                        tx,
                        existing_report["id"],
                        country_id=country_id,
                        explicit_report_spec=report_spec,
                        report_spec_schema_version=report_spec_schema_version,
                    )

                self._require_simulation_exists(
                    tx,
                    country_id=country_id,
                    simulation_id=simulation_1_id,
                )
                if simulation_2_id is not None:
                    self._require_simulation_exists(
                        tx,
                        country_id=country_id,
                        simulation_id=simulation_2_id,
                    )

                if simulation_2_id is not None:
                    tx.query(
                        """
                        INSERT INTO report_outputs (
                            country_id, simulation_1_id, simulation_2_id, api_version, status, year
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
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
                    tx.query(
                        """
                        INSERT INTO report_outputs (
                            country_id, simulation_1_id, api_version, status, year
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            country_id,
                            simulation_1_id,
                            api_version,
                            "pending",
                            year,
                        ),
                    )

                created_report = self._find_existing_report_output_row(
                    country_id=country_id,
                    simulation_1_id=simulation_1_id,
                    simulation_2_id=simulation_2_id,
                    year=year,
                    queryer=tx,
                )
                if created_report is None:
                    raise Exception("Failed to retrieve created report output")

                print(f"Created report output with ID: {created_report['id']}")
                return self._ensure_report_output_dual_write_state_in_transaction(
                    tx,
                    created_report["id"],
                    country_id=country_id,
                    explicit_report_spec=report_spec,
                    report_spec_schema_version=report_spec_schema_version,
                )

            return database.transaction(tx_callback)

        except Exception as e:
            print(f"Error creating report output. Details: {str(e)}")
            raise e

    def get_report_output(self, country_id: str, report_output_id: int) -> dict | None:
        """
        Get a report output record by ID.
        """
        print(f"Getting report output {report_output_id}")

        try:
            if type(report_output_id) is not int or report_output_id < 0:
                raise Exception(
                    f"Invalid report output ID: {report_output_id}. Must be a positive integer."
                )

            report_output = self._get_report_output_row(
                report_output_id,
                country_id=country_id,
            )
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
        version_manifest_overrides: dict[str, str | None] | None = None,
    ) -> bool:
        """
        Update a report output record with results or error.
        """
        print(f"Updating report output {report_id}")

        try:
            update_fields = []
            update_values = []

            if status is not None:
                update_fields.append("status = ?")
                update_values.append(status)

            if output is not None:
                update_fields.append("output = ?")
                update_values.append(output)

            if error_message is not None:
                update_fields.append("error_message = ?")
                update_values.append(error_message)

            if not update_fields and not version_manifest_overrides:
                print("No fields to update")
                return False

            def tx_callback(tx):
                requested_report = self._get_report_output_row(
                    report_id,
                    queryer=tx,
                    country_id=country_id,
                    for_update=True,
                )
                if requested_report is None:
                    raise ValueError(f"Report output #{report_id} not found")

                if update_fields:
                    tx.query(
                        f"UPDATE report_outputs SET {', '.join(update_fields)} WHERE id = ? AND country_id = ?",
                        (*update_values, report_id, country_id),
                    )
                self._ensure_report_output_dual_write_state_in_transaction(
                    tx,
                    report_id,
                    country_id=country_id,
                    version_manifest_overrides=version_manifest_overrides,
                )

            database.transaction(tx_callback)

            print(f"Successfully updated report output #{report_id}")
            return True

        except Exception as e:
            print(f"Error updating report output #{report_id}. Details: {str(e)}")
            raise e
