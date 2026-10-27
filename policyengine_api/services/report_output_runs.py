"""The run history of v1 report outputs: each write mirrored into a report run."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import ReportOutput, ReportOutputRun, Simulation
from policyengine_api.services.report_run_service import NewReportOutputRun
from policyengine_api.services.report_spec_service import (
    ECONOMY_REPORT_KINDS,
    ReportSpec,
)


class ReportOutputRunHistoryMixin:
    """Keep a report output's run history and spec in step with the report."""

    @staticmethod
    def _utc_timestamp() -> datetime:
        return datetime.now(UTC).replace(microsecond=0, tzinfo=None)

    @staticmethod
    def format_run_timestamp(value: datetime | str | None) -> str | None:
        """Return a timestamp as an ISO 8601 UTC string ending in ``Z``, or None.

        Naive values are taken as UTC; an unparseable string is returned with ``Z``
        added.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            timestamp = value
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            return (
                timestamp.astimezone(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        timestamp = str(value).strip()
        if not timestamp:
            return None
        normalized = timestamp.replace(" ", "T", 1)
        parseable = (
            f"{normalized[:-1]}+00:00" if normalized.endswith("Z") else normalized
        )
        try:
            parsed = datetime.fromisoformat(parseable)
        except ValueError:
            return normalized if normalized.endswith("Z") else f"{normalized}Z"
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (
            parsed.astimezone(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _list_runs_descending(
        session: Session, report_output_id: int
    ) -> list[ReportOutputRun]:
        return list(
            session.scalars(
                select(ReportOutputRun)
                .where(ReportOutputRun.report_output_id == report_output_id)
                .order_by(ReportOutputRun.run_sequence.desc())
            )
        )

    def _get_linked_simulations(
        self,
        session: Session,
        report_output: ReportOutput,
        *,
        bootstrap_dual_write_state: bool,
    ) -> tuple[Simulation, Simulation | None]:
        def get_simulation(simulation_id: int) -> Simulation | None:
            if bootstrap_dual_write_state:
                try:
                    return self.simulation_service.ensure_simulation_dual_write_state(
                        session,
                        simulation_id,
                        report_output.country_id,
                    )
                except ValueError:
                    return None
            return session.scalar(
                select(Simulation).where(
                    Simulation.id == simulation_id,
                    Simulation.country_id == report_output.country_id,
                )
            )

        simulation_1 = get_simulation(report_output.simulation_1_id)
        if simulation_1 is None:
            msg = (
                "Report output references missing simulation "
                f"#{report_output.simulation_1_id}"
            )
            raise ValueError(msg)
        simulation_2 = None
        if report_output.simulation_2_id is not None:
            simulation_2 = get_simulation(report_output.simulation_2_id)
            if simulation_2 is None:
                msg = (
                    "Report output references missing simulation "
                    f"#{report_output.simulation_2_id}"
                )
                raise ValueError(msg)
        return simulation_1, simulation_2

    @staticmethod
    def _select_mutable_run(
        report_output: ReportOutput, runs_descending: list[ReportOutputRun]
    ) -> ReportOutputRun | None:
        if report_output.status == "running":
            if report_output.active_run_id is not None:
                active = next(
                    (
                        run
                        for run in runs_descending
                        if run.id == report_output.active_run_id
                        and run.status in {"pending", "running"}
                    ),
                    None,
                )
                if active is not None:
                    return active
            return next(
                (
                    run
                    for run in runs_descending
                    if run.status in {"pending", "running"}
                ),
                None,
            )
        if report_output.active_run_id is not None:
            active = next(
                (
                    run
                    for run in runs_descending
                    if run.id == report_output.active_run_id
                ),
                None,
            )
            if active is not None:
                return active
        return runs_descending[0] if runs_descending else None

    @staticmethod
    def _run_needs_timestamp_sync(run: ReportOutputRun, status: str) -> bool:
        if run.requested_at is None:
            return True
        if status in {"complete", "error"}:
            return run.started_at is None or run.finished_at is None
        if status == "running":
            return run.started_at is None or run.finished_at is not None
        return run.started_at is not None or run.finished_at is not None

    @staticmethod
    def _has_mutable_running_run(
        report_output: ReportOutput, runs_descending: list[ReportOutputRun]
    ) -> bool:
        if not runs_descending:
            return True
        if report_output.active_run_id is not None:
            active = next(
                (
                    run
                    for run in runs_descending
                    if run.id == report_output.active_run_id
                ),
                None,
            )
            return active is not None and active.status in {"pending", "running"}
        return any(run.status in {"pending", "running"} for run in runs_descending)

    @staticmethod
    def _derive_country_package_version(
        simulation_1: Simulation | None,
        simulation_2: Simulation | None,
    ) -> str | None:
        versions = [
            simulation.api_version
            for simulation in (simulation_1, simulation_2)
            if simulation is not None and simulation.api_version is not None
        ]
        return versions[0] if versions and len(set(versions)) == 1 else None

    def _build_version_manifest(
        self,
        report_output: ReportOutput,
        report_spec: ReportSpec | None,
        simulation_1: Simulation | None,
        simulation_2: Simulation | None,
    ) -> dict[str, str | None]:
        return {
            "country_package_version": self._derive_country_package_version(
                simulation_1, simulation_2
            ),
            "policyengine_version": None,
            "data_version": None,
            "runtime_app_name": None,
            "report_cache_version": report_output.api_version,
            "simulation_cache_version": None,
            "requested_version_override": None,
            "resolved_dataset": (
                report_spec.dataset
                if report_spec is not None
                and report_spec.report_kind in ECONOMY_REPORT_KINDS
                else None
            ),
            "resolved_options_hash": None,
        }

    @staticmethod
    def _report_spec_status(report_spec: ReportSpec) -> str:
        return (
            "backfilled_assumed"
            if report_spec.report_kind in ECONOMY_REPORT_KINDS
            else "explicit"
        )

    def _upsert_report_spec(
        self,
        report_output: ReportOutput,
        simulation_1: Simulation | None,
        simulation_2: Simulation | None,
    ) -> ReportSpec | None:
        if simulation_1 is None:
            return None
        try:
            report_spec = self.report_spec_service.build_report_spec(
                report_output, simulation_1, simulation_2
            )
        except ValueError:
            return None
        report_output.report_kind = report_spec.report_kind
        report_output.report_spec_json = report_spec.model_dump()
        report_output.report_spec_schema_version = 1
        report_output.report_spec_status = self._report_spec_status(report_spec)
        return report_spec

    @staticmethod
    def _run_matches_parent(
        run: ReportOutputRun,
        report_output: ReportOutput,
        report_spec: ReportSpec | None,
        version_manifest: dict[str, str | None],
    ) -> bool:
        return (
            run.status == report_output.status
            and run.output == report_output.output
            and run.error_message == report_output.error_message
            and run.report_spec_snapshot_json
            == (report_spec.model_dump() if report_spec else None)
            and all(
                getattr(run, field) == value
                for field, value in version_manifest.items()
            )
        )

    def _update_run_from_parent(
        self,
        run: ReportOutputRun,
        report_output: ReportOutput,
        report_spec: ReportSpec | None,
        version_manifest: dict[str, str | None],
        *,
        preserve_terminal_finished_at: bool,
    ) -> None:
        now = self._utc_timestamp()
        run.requested_at = run.requested_at or run.started_at or run.finished_at or now
        if report_output.status in {"complete", "error"}:
            run.started_at = (
                run.started_at or run.finished_at or run.requested_at or now
            )
            if not preserve_terminal_finished_at or run.finished_at is None:
                run.finished_at = now
        elif report_output.status == "running":
            run.started_at = run.started_at or run.requested_at or now
            run.finished_at = None
        else:
            run.started_at = None
            run.finished_at = None
        run.status = report_output.status
        run.output = report_output.output
        run.error_message = report_output.error_message
        run.report_spec_snapshot_json = (
            report_spec.model_dump() if report_spec else None
        )
        for field, value in version_manifest.items():
            setattr(run, field, value)

    @staticmethod
    def _sync_parent_pointers(
        report_output: ReportOutput, runs_descending: list[ReportOutputRun]
    ) -> None:
        latest_successful = next(
            (run.id for run in runs_descending if run.status == "complete"), None
        )
        if report_output.status in {"pending", "running"} and runs_descending:
            report_output.active_run_id = runs_descending[0].id
        else:
            report_output.active_run_id = None
        if report_output.status == "complete" and latest_successful is None:
            latest_successful = runs_descending[0].id if runs_descending else None
        report_output.latest_successful_run_id = latest_successful

    def _ensure_report_output_dual_write_state(
        self,
        session: Session,
        report_output_id: int,
        country_id: str | None = None,
    ) -> ReportOutput:
        report_output = self._select_report_output(
            session, report_output_id, country_id, for_update=True
        )
        if report_output is None:
            msg = f"Report output #{report_output_id} not found"
            raise ValueError(msg)
        try:
            simulation_1, simulation_2 = self._get_linked_simulations(
                session,
                report_output,
                bootstrap_dual_write_state=True,
            )
        except ValueError:
            simulation_1, simulation_2 = None, None
        report_spec = self._upsert_report_spec(
            report_output, simulation_1, simulation_2
        )
        manifest = self._build_version_manifest(
            report_output, report_spec, simulation_1, simulation_2
        )
        runs = self._list_runs_descending(session, report_output_id)
        if not runs:
            self.report_run_service.create_report_output_run(
                session,
                report_output_id,
                NewReportOutputRun(
                    status=report_output.status,
                    output=report_output.output,
                    error_message=report_output.error_message,
                    trigger_type="initial",
                    report_spec_snapshot=(
                        report_spec.model_dump() if report_spec else None
                    ),
                    version_manifest=manifest,
                ),
            )
            runs = self._list_runs_descending(session, report_output_id)
        else:
            mutable = self._select_mutable_run(report_output, runs)
            if mutable is not None:
                matches_result = (
                    mutable.status == report_output.status
                    and mutable.output == report_output.output
                    and mutable.error_message == report_output.error_message
                )
                if not self._run_matches_parent(
                    mutable, report_output, report_spec, manifest
                ) or self._run_needs_timestamp_sync(mutable, report_output.status):
                    self._update_run_from_parent(
                        mutable,
                        report_output,
                        report_spec,
                        manifest,
                        preserve_terminal_finished_at=matches_result,
                    )
                    session.flush()
                    runs = self._list_runs_descending(session, report_output_id)
        self._sync_parent_pointers(report_output, runs)
        session.flush()
        return report_output
