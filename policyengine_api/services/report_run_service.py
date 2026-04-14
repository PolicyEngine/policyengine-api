import json
import uuid
from typing import Any

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


class ReportRunService:
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
        run_id = run_id or str(uuid.uuid4())
        run_sequence = self._next_run_sequence(report_output_id)
        version_manifest = version_manifest or {}

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
                *[version_manifest.get(field) for field in REPORT_RUN_VERSION_FIELDS],
            ),
        )
        return self.get_report_output_run(run_id)

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
            return self.get_report_output_run(report_output["active_run_id"])
        if report_output.get("latest_successful_run_id"):
            return self.get_report_output_run(report_output["latest_successful_run_id"])
        return self.get_newest_report_output_run(report_output["id"])
