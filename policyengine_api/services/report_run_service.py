import json
import uuid
from datetime import datetime, timezone
from typing import Any

from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import ReportDAO, V1UnitOfWork
from policyengine_api.services.run_sync_utils import select_display_report_run


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
    def __init__(
        self,
        reports: ReportDAO | None = None,
        *,
        unit_of_work: V1UnitOfWork | None = None,
    ):
        self._reports = reports
        self._unit_of_work = unit_of_work

    @property
    def unit_of_work(self) -> V1UnitOfWork:
        if self._unit_of_work is None:
            self._unit_of_work = V1UnitOfWork(build_v1_session_manager())
        return self._unit_of_work

    def _parse_run_row(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        run = dict(row)
        if isinstance(run.get("report_spec_snapshot_json"), str):
            run["report_spec_snapshot_json"] = json.loads(
                run["report_spec_snapshot_json"]
            )
        for field in ("requested_at", "started_at", "finished_at"):
            if isinstance(run.get(field), datetime):
                run[field] = run[field].strftime("%Y-%m-%d %H:%M:%S")
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
        now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
        terminal = status in ("complete", "error")
        started = status in ("running", "complete", "error")
        values = {
            "status": status,
            "output": output,
            "error_message": error_message,
            "trigger_type": trigger_type,
            "requested_at": now,
            "started_at": now if started else None,
            "finished_at": now if terminal else None,
            "source_run_id": source_run_id,
            "report_spec_snapshot_json": report_spec_snapshot,
        }
        values.update(
            {
                field: (version_manifest or {}).get(field)
                for field in REPORT_RUN_VERSION_FIELDS
            }
        )
        try:
            if self._reports is not None:
                run = self._reports.create_run(
                    report_output_id,
                    run_id=run_id or str(uuid.uuid4()),
                    **values,
                )
            else:
                with self.unit_of_work.transaction() as daos:
                    run = daos.reports.create_run(
                        report_output_id,
                        run_id=run_id or str(uuid.uuid4()),
                        **values,
                    )
        except LookupError as error:
            raise ValueError(f"Report output #{report_output_id} not found") from error
        return self._parse_run_row(run)

    def get_report_output_run(self, run_id: str) -> dict | None:
        if self._reports is not None:
            return self._parse_run_row(self._reports.get_run(run_id))
        with self.unit_of_work.read() as daos:
            return self._parse_run_row(daos.reports.get_run(run_id))

    def list_report_output_runs(self, report_output_id: int) -> list[dict]:
        if self._reports is not None:
            rows = self._reports.list_runs(report_output_id)
        else:
            with self.unit_of_work.read() as daos:
                rows = daos.reports.list_runs(report_output_id)
        return [self._parse_run_row(row) for row in reversed(rows)]

    def get_newest_report_output_run(self, report_output_id: int) -> dict | None:
        if self._reports is not None:
            rows = self._reports.list_runs(report_output_id)
        else:
            with self.unit_of_work.read() as daos:
                rows = daos.reports.list_runs(report_output_id)
        return self._parse_run_row(rows[0]) if rows else None

    def select_display_run(self, report_output: dict) -> dict | None:
        runs_descending = list(
            reversed(self.list_report_output_runs(report_output["id"]))
        )
        return select_display_report_run(report_output, runs_descending)
