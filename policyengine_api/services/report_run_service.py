import json
import sqlite3
import uuid
from typing import Any

import sqlalchemy.exc
from sqlalchemy.engine.row import Row

from policyengine_api.data import database


REPORT_RUN_VERSION_FIELDS = (
    "country_package_version",
    "policyengine_version",
    "data_version",
    "runtime_app_name",
    "report_cache_version",
    "simulation_cache_version",
    "requested_version_override",
    "resolved_dataset",
    "resolved_options_hash",
)
MAX_CREATE_RUN_ATTEMPTS = 3


class ReportRunService:
    def _report_output_exists(self, report_output_id: int) -> bool:
        row: Row | None = database.query(
            "SELECT id FROM report_outputs WHERE id = ?",
            (report_output_id,),
        ).fetchone()
        return row is not None

    def _next_run_sequence(self, report_output_id: int) -> int:
        row: Row | None = database.query(
            """
            SELECT COALESCE(MAX(run_sequence), 0) AS max_run_sequence
            FROM report_output_runs
            WHERE report_output_id = ?
            """,
            (report_output_id,),
        ).fetchone()
        return int(row["max_run_sequence"]) + 1 if row is not None else 1

    def _serialize_json(
        self, value: dict[str, Any] | list[Any] | str | None
    ) -> str | None:
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value)

    def _parse_run_row(self, row: Row | dict | None) -> dict | None:
        if row is None:
            return None

        run = dict(row)
        if isinstance(run.get("report_spec_snapshot_json"), str):
            run["report_spec_snapshot_json"] = json.loads(
                run["report_spec_snapshot_json"]
            )
        return run

    def _is_sequence_conflict(self, error: Exception) -> bool:
        message = str(error)
        return (
            "report_output_run_sequence_idx" in message
            or "report_output_runs.report_output_id, report_output_runs.run_sequence"
            in message
        )

    def create_report_output_run(
        self,
        report_output_id: int,
        status: str = "pending",
        trigger_type: str = "initial",
        output: dict[str, Any] | list[Any] | str | None = None,
        error_message: str | None = None,
        source_run_id: str | None = None,
        report_spec_snapshot: dict[str, Any] | str | None = None,
        version_manifest: dict[str, str | None] | None = None,
        run_id: str | None = None,
    ) -> dict:
        if not self._report_output_exists(report_output_id):
            raise ValueError(f"Report output #{report_output_id} not found")

        run_id = run_id or str(uuid.uuid4())
        version_manifest = version_manifest or {}

        for attempt in range(MAX_CREATE_RUN_ATTEMPTS):
            run_sequence = self._next_run_sequence(report_output_id)
            try:
                database.query(
                    f"""
                    INSERT INTO report_output_runs (
                        id, report_output_id, run_sequence, status, output, error_message,
                        trigger_type, requested_at, started_at, finished_at, source_run_id,
                        report_spec_snapshot_json, {", ".join(REPORT_RUN_VERSION_FIELDS)}
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        report_output_id,
                        run_sequence,
                        status,
                        self._serialize_json(output),
                        error_message,
                        trigger_type,
                        None,
                        None,
                        None,
                        source_run_id,
                        self._serialize_json(report_spec_snapshot),
                        *[
                            version_manifest.get(field)
                            for field in REPORT_RUN_VERSION_FIELDS
                        ],
                    ),
                )
                return self.get_report_output_run(run_id)
            except (sqlite3.IntegrityError, sqlalchemy.exc.IntegrityError) as error:
                if (
                    attempt == MAX_CREATE_RUN_ATTEMPTS - 1
                    or not self._is_sequence_conflict(error)
                ):
                    raise

        raise RuntimeError(
            f"Unable to allocate report output run sequence for #{report_output_id}"
        )

    def get_report_output_run(self, run_id: str) -> dict | None:
        row: Row | None = database.query(
            "SELECT * FROM report_output_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return self._parse_run_row(row)

    def list_report_output_runs(self, report_output_id: int) -> list[dict]:
        rows = database.query(
            """
            SELECT * FROM report_output_runs
            WHERE report_output_id = ?
            ORDER BY run_sequence ASC
            """,
            (report_output_id,),
        ).fetchall()
        return [self._parse_run_row(row) for row in rows]

    def get_newest_report_output_run(self, report_output_id: int) -> dict | None:
        row: Row | None = database.query(
            """
            SELECT * FROM report_output_runs
            WHERE report_output_id = ?
            ORDER BY run_sequence DESC
            LIMIT 1
            """,
            (report_output_id,),
        ).fetchone()
        return self._parse_run_row(row)

    def select_display_run(self, report_output: dict) -> dict | None:
        if report_output.get("active_run_id"):
            active_run = self.get_report_output_run(report_output["active_run_id"])
            if active_run is not None:
                return active_run
        if report_output.get("latest_successful_run_id"):
            latest_successful_run = self.get_report_output_run(
                report_output["latest_successful_run_id"]
            )
            if latest_successful_run is not None:
                return latest_successful_run
        return self.get_newest_report_output_run(report_output["id"])
