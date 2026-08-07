import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import ReportOutput, ReportOutputRun


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
    """Report-run operations performed through a caller-owned ORM Session."""

    @staticmethod
    def _matches_report_result(run: ReportOutputRun, report: ReportOutput) -> bool:
        return (
            run.status == report.status
            and run.output == report.output
            and run.error_message == report.error_message
        )

    def create_report_output_run(
        self,
        session: Session,
        report_output_id: int,
        status: str = "pending",
        trigger_type: str = "initial",
        output: dict[str, Any] | list[Any] | None = None,
        error_message: str | None = None,
        source_run_id: str | None = None,
        report_spec_snapshot: dict[str, Any] | None = None,
        version_manifest: dict[str, str | None] | None = None,
        run_id: str | None = None,
    ) -> ReportOutputRun:
        parent = session.scalar(
            select(ReportOutput)
            .where(ReportOutput.id == report_output_id)
            .with_for_update()
        )
        if parent is None:
            raise ValueError(f"Report output #{report_output_id} not found")
        sequence = (
            session.scalar(
                select(func.max(ReportOutputRun.run_sequence)).where(
                    ReportOutputRun.report_output_id == report_output_id
                )
            )
            or 0
        ) + 1
        now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
        values = {
            "status": status,
            "output": output,
            "error_message": error_message,
            "trigger_type": trigger_type,
            "requested_at": now,
            "started_at": now if status in {"running", "complete", "error"} else None,
            "finished_at": now if status in {"complete", "error"} else None,
            "source_run_id": source_run_id,
            "report_spec_snapshot_json": report_spec_snapshot,
        }
        values.update(
            {
                field: (version_manifest or {}).get(field)
                for field in REPORT_RUN_VERSION_FIELDS
            }
        )
        run = ReportOutputRun(
            id=run_id or str(uuid.uuid4()),
            report_output_id=report_output_id,
            run_sequence=sequence,
            **values,
        )
        session.add(run)
        session.flush()
        return run

    def get_report_output_run(
        self, session: Session, run_id: str
    ) -> ReportOutputRun | None:
        return session.get(ReportOutputRun, run_id)

    def list_report_output_runs(
        self, session: Session, report_output_id: int
    ) -> list[ReportOutputRun]:
        return list(
            session.scalars(
                select(ReportOutputRun)
                .where(ReportOutputRun.report_output_id == report_output_id)
                .order_by(ReportOutputRun.run_sequence.asc())
            )
        )

    def get_newest_report_output_run(
        self, session: Session, report_output_id: int
    ) -> ReportOutputRun | None:
        return session.scalar(
            select(ReportOutputRun)
            .where(ReportOutputRun.report_output_id == report_output_id)
            .order_by(ReportOutputRun.run_sequence.desc())
        )

    def select_display_run(
        self, session: Session, report_output: ReportOutput
    ) -> ReportOutputRun | None:
        runs = list(
            session.scalars(
                select(ReportOutputRun)
                .where(ReportOutputRun.report_output_id == report_output.id)
                .order_by(ReportOutputRun.run_sequence.desc())
            )
        )
        if report_output.active_run_id is not None:
            active = next(
                (run for run in runs if run.id == report_output.active_run_id), None
            )
            if active is not None:
                return active
        if report_output.status == "error":
            matching_error = next(
                (
                    run
                    for run in runs
                    if self._matches_report_result(run, report_output)
                ),
                None,
            )
            if matching_error is not None:
                return matching_error
        if report_output.latest_successful_run_id is not None:
            successful = next(
                (
                    run
                    for run in runs
                    if run.id == report_output.latest_successful_run_id
                ),
                None,
            )
            if successful is not None:
                return successful
        matching = next(
            (run for run in runs if self._matches_report_result(run, report_output)),
            None,
        )
        return matching or (runs[0] if runs else None)
