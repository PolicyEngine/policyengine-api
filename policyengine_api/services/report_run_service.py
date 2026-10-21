"""Run history for v1 report outputs, one numbered row per calculation attempt."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
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


@dataclass(frozen=True)
class NewReportOutputRun:
    """The fields of a report-output run to append; omitted fields take these defaults.

    ``version_manifest`` supplies the run's version fields, and ``run_id`` a fixed
    ID instead of a new UUID.
    """

    status: str = "pending"
    trigger_type: str = "initial"
    output: dict[str, Any] | list[Any] | None = None
    error_message: str | None = None
    source_run_id: str | None = None
    report_spec_snapshot: dict[str, Any] | None = None
    version_manifest: dict[str, str | None] | None = None
    run_id: str | None = None


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
        new_run: NewReportOutputRun | None = None,
    ) -> ReportOutputRun:
        """Append the next numbered run to a report output and return it.

        ``new_run`` gives the run's fields; without it the run takes the defaults.
        The parent row is locked while the sequence number is chosen, and timestamps are
        set to now according to its ``status``. Raise ValueError if the report output
        does not exist. The caller owns the transaction.
        """
        if new_run is None:
            new_run = NewReportOutputRun()
        status = new_run.status
        parent = session.scalar(
            select(ReportOutput)
            .where(ReportOutput.id == report_output_id)
            .with_for_update()
        )
        if parent is None:
            msg = f"Report output #{report_output_id} not found"
            raise ValueError(msg)
        sequence = (
            session.scalar(
                select(func.max(ReportOutputRun.run_sequence)).where(
                    ReportOutputRun.report_output_id == report_output_id
                )
            )
            or 0
        ) + 1
        now = datetime.now(UTC).replace(microsecond=0, tzinfo=None)
        values = {
            "status": status,
            "output": new_run.output,
            "error_message": new_run.error_message,
            "trigger_type": new_run.trigger_type,
            "requested_at": now,
            "started_at": now if status in {"running", "complete", "error"} else None,
            "finished_at": now if status in {"complete", "error"} else None,
            "source_run_id": new_run.source_run_id,
            "report_spec_snapshot_json": new_run.report_spec_snapshot,
        }
        values.update(
            {
                field: (new_run.version_manifest or {}).get(field)
                for field in REPORT_RUN_VERSION_FIELDS
            }
        )
        run = ReportOutputRun(
            id=new_run.run_id or str(uuid.uuid4()),
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
        """Return the run with this ID, or None."""
        return session.get(ReportOutputRun, run_id)

    def list_report_output_runs(
        self, session: Session, report_output_id: int
    ) -> list[ReportOutputRun]:
        """Return all runs of a report output, oldest first."""
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
        """Return the report output's highest-numbered run, or None if it has none."""
        return session.scalar(
            select(ReportOutputRun)
            .where(ReportOutputRun.report_output_id == report_output_id)
            .order_by(ReportOutputRun.run_sequence.desc())
        )

    def select_display_run(
        self, session: Session, report_output: ReportOutput
    ) -> ReportOutputRun | None:
        """Return the run whose result the report output should display, or None.

        Prefer the active run, then (for a failed report) the run holding its error,
        then the latest successful run, then any run matching the report's result, and
        finally the newest run.
        """
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
