import uuid
from datetime import datetime, timezone

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import V1UnitOfWork
from policyengine_api.services.report_spec_service import (
    ECONOMY_REPORT_KINDS,
    ReportSpec,
    ReportSpecService,
)
from policyengine_api.services.run_sync_utils import (
    determine_parent_pointers,
    parse_json_field,
    run_matches_report_result,
    select_display_report_run,
    serialize_json_field,
)


class ReportOutputService:
    def __init__(self, *, unit_of_work: V1UnitOfWork | None = None):
        self._unit_of_work = unit_of_work
        self.report_spec_service = ReportSpecService()

    @property
    def unit_of_work(self) -> V1UnitOfWork:
        if self._unit_of_work is None:
            self._unit_of_work = V1UnitOfWork(build_v1_session_manager())
        return self._unit_of_work

    def _utc_timestamp(self) -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)

    def _format_run_timestamp(self, value) -> str | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            timestamp = value
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return (
                timestamp.astimezone(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )

        timestamp = str(value).strip()
        if not timestamp:
            return None

        normalized = timestamp.replace(" ", "T", 1)
        parseable_timestamp = (
            f"{normalized[:-1]}+00:00" if normalized.endswith("Z") else normalized
        )
        try:
            parsed = datetime.fromisoformat(parseable_timestamp)
        except ValueError:
            if "T" in normalized:
                return normalized if normalized.endswith("Z") else f"{normalized}Z"
            return f"{normalized}Z"

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (
            parsed.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _get_report_output_row(
        self,
        report_output_id: int,
        *,
        queryer=None,
        country_id: str | None = None,
        for_update: bool = False,
    ) -> dict | None:
        if queryer is None:
            with self.unit_of_work.read() as daos:
                return self._get_report_output_row(
                    report_output_id,
                    queryer=daos,
                    country_id=country_id,
                    for_update=for_update,
                )
        if for_update:
            return queryer.reports.get_for_update(report_output_id, country_id)
        return queryer.reports.get(report_output_id, country_id)

    def _get_linked_simulations(
        self,
        report_output: dict,
        *,
        queryer=None,
        bootstrap_dual_write_state: bool = False,
    ) -> tuple[dict, dict | None]:
        if queryer is None:
            with self.unit_of_work.read() as daos:
                return self._get_linked_simulations(
                    report_output,
                    queryer=daos,
                    bootstrap_dual_write_state=bootstrap_dual_write_state,
                )
        if bootstrap_dual_write_state:
            simulation_1 = queryer.simulations.ensure_dual_write_state(
                report_output["simulation_1_id"],
                report_output["country_id"],
            )
        else:
            simulation_1 = queryer.simulations.get(
                report_output["simulation_1_id"],
                report_output["country_id"],
            )
        if simulation_1 is None:
            raise ValueError(
                "Report output references missing simulation "
                f"#{report_output['simulation_1_id']}"
            )

        simulation_2 = None
        if report_output["simulation_2_id"] is not None:
            if bootstrap_dual_write_state:
                simulation_2 = queryer.simulations.ensure_dual_write_state(
                    report_output["simulation_2_id"],
                    report_output["country_id"],
                )
            else:
                simulation_2 = queryer.simulations.get(
                    report_output["simulation_2_id"],
                    report_output["country_id"],
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
        simulation = tx.simulations.get(simulation_id, country_id)
        if simulation is None:
            raise ValueError(
                f"Report output references missing simulation #{simulation_id}"
            )
        return simulation

    def _list_report_runs_descending(
        self, report_output_id: int, *, queryer=None
    ) -> list[dict]:
        if queryer is None:
            with self.unit_of_work.read() as daos:
                return self._list_report_runs_descending(
                    report_output_id,
                    queryer=daos,
                )
        rows = queryer.reports.list_runs(report_output_id)

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
        if report_output["status"] == "running":
            if active_run_id is not None:
                for run in runs_descending:
                    if run["id"] == active_run_id and run["status"] in (
                        "pending",
                        "running",
                    ):
                        return run
            for run in runs_descending:
                if run["status"] in ("pending", "running"):
                    return run
            return None
        if active_run_id is not None:
            for run in runs_descending:
                if run["id"] == active_run_id:
                    return run
        return runs_descending[0] if runs_descending else None

    def _has_mutable_running_run(self, report_output: dict, *, queryer=None) -> bool:
        runs_descending = self._list_report_runs_descending(
            report_output["id"], queryer=queryer
        )
        if not runs_descending:
            return True

        active_run_id = report_output.get("active_run_id")
        if active_run_id is not None:
            for run in runs_descending:
                if run["id"] == active_run_id:
                    return run["status"] in ("pending", "running")
            return False

        return any(run["status"] in ("pending", "running") for run in runs_descending)

    def _run_needs_timestamp_sync(self, run: dict, status: str) -> bool:
        if run.get("requested_at") is None:
            return True
        if status in ("complete", "error"):
            return run.get("started_at") is None or run.get("finished_at") is None
        if status == "running":
            return run.get("started_at") is None or run.get("finished_at") is not None
        return run.get("started_at") is not None or run.get("finished_at") is not None

    def _with_display_run_timestamps(
        self, report_output: dict, *, queryer=None
    ) -> dict:
        """
        Overlay selected run timestamps onto the legacy report response shape.

        This is a response-compatibility bridge for app-v2 while report output
        reads still return a report_outputs row. The authoritative timestamp
        values live on report_output_runs; this helper chooses the display run,
        formats its requested/started/finished timestamps, and returns an
        enriched copy of the report output dict. It intentionally does not
        mutate repository state.

        These timestamps describe the selected base report execution. They are
        not user-report association metadata and should not be treated as a
        user-specific "last run" value.

        TODO: When report output reads are cut over to canonical run-backed
        resolution, move this projection into the final response serializer
        instead of keeping it as an ad hoc enrichment helper.
        """
        runs_descending = self._list_report_runs_descending(
            report_output["id"], queryer=queryer
        )
        display_run = select_display_report_run(report_output, runs_descending)
        enriched_report_output = dict(report_output)
        enriched_report_output["output"] = serialize_json_field(
            enriched_report_output.get("output")
        )
        if display_run is None:
            return enriched_report_output

        for field in ("requested_at", "started_at", "finished_at"):
            enriched_report_output[field] = self._format_run_timestamp(
                display_run.get(field)
            )
        return enriched_report_output

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
    ) -> dict[str, str | None]:
        resolved_dataset = None
        if report_spec is not None and report_spec.report_kind in ECONOMY_REPORT_KINDS:
            resolved_dataset = report_spec.dataset

        return {
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

    def _get_report_spec_status(self, report_spec: ReportSpec) -> str:
        if report_spec.report_kind in ECONOMY_REPORT_KINDS:
            return "backfilled_assumed"
        return "explicit"

    def _upsert_report_spec_in_transaction(
        self,
        tx,
        report_output: dict,
        simulation_1: dict | None,
        simulation_2: dict | None,
    ) -> ReportSpec | None:
        if simulation_1 is None:
            return None

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
            tx.reports.update(
                report_output["id"],
                report_kind=report_spec.report_kind,
                report_spec_json=report_spec.model_dump(),
                report_spec_schema_version=1,
                report_spec_status=report_spec_status,
            )
            report_output["report_kind"] = report_spec.report_kind
            report_output["report_spec_json"] = report_spec.model_dump()
            report_output["report_spec_schema_version"] = 1
            report_output["report_spec_status"] = report_spec_status

        return report_spec

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
        requested_at = self._utc_timestamp()
        is_terminal = report_output["status"] in ("complete", "error")
        has_started = report_output["status"] in ("running", "complete", "error")
        started_at = requested_at if has_started else None
        finished_at = requested_at if is_terminal else None

        tx.reports.create_run(
            report_output["id"],
            run_id=str(uuid.uuid4()),
            status=report_output["status"],
            output=report_output.get("output"),
            error_message=report_output.get("error_message"),
            trigger_type="initial",
            requested_at=requested_at,
            started_at=started_at,
            finished_at=finished_at,
            source_run_id=None,
            report_spec_snapshot_json=(
                report_spec.model_dump() if report_spec is not None else None
            ),
            **version_manifest,
        )

    def _update_report_run_in_transaction(
        self,
        tx,
        run_id: str,
        report_output: dict,
        report_spec: ReportSpec | None,
        version_manifest: dict[str, str | None],
        preserve_terminal_finished_at: bool = False,
    ) -> None:
        run = tx.reports.get_run(run_id)
        if run is None:
            raise ValueError(f"Report output run {run_id} not found")

        fallback_timestamp = self._utc_timestamp()
        requested_at = (
            run.get("requested_at")
            or run.get("started_at")
            or run.get("finished_at")
            or fallback_timestamp
        )
        if report_output["status"] in ("complete", "error"):
            finished_at = self._utc_timestamp()
            started_at = (
                run.get("started_at")
                or run.get("finished_at")
                or run.get("requested_at")
                or finished_at
            )
            if preserve_terminal_finished_at:
                finished_at = run.get("finished_at") or finished_at
        elif report_output["status"] == "running":
            started_at = (
                run.get("started_at")
                or run.get("requested_at")
                or self._utc_timestamp()
            )
            finished_at = None
        else:
            started_at = None
            finished_at = None

        tx.reports.update_run(
            run_id,
            status=report_output["status"],
            output=report_output.get("output"),
            error_message=report_output.get("error_message"),
            requested_at=requested_at,
            started_at=started_at,
            finished_at=finished_at,
            report_spec_snapshot_json=(
                report_spec.model_dump() if report_spec is not None else None
            ),
            **version_manifest,
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

        tx.reports.update(
            report_output["id"],
            active_run_id=desired_active_run_id,
            latest_successful_run_id=desired_latest_successful_run_id,
        )
        report_output["active_run_id"] = desired_active_run_id
        report_output["latest_successful_run_id"] = desired_latest_successful_run_id

    def _ensure_report_output_dual_write_state_in_transaction(
        self,
        tx,
        report_output_id: int,
        *,
        country_id: str | None = None,
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
        )
        version_manifest = self._build_version_manifest(
            report_output,
            report_spec=report_spec,
            simulation_1=simulation_1,
            simulation_2=simulation_2,
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
            if mutable_run is not None:
                run_matches_parent = self._run_matches_parent(
                    mutable_run,
                    report_output,
                    report_spec,
                    version_manifest,
                )
                needs_timestamp_sync = self._run_needs_timestamp_sync(
                    mutable_run, report_output["status"]
                )
                if not run_matches_parent or needs_timestamp_sync:
                    run_matches_result = run_matches_report_result(
                        mutable_run, report_output
                    )
                    self._update_report_run_in_transaction(
                        tx,
                        run_id=mutable_run["id"],
                        report_output=report_output,
                        report_spec=report_spec,
                        version_manifest=version_manifest,
                        preserve_terminal_finished_at=run_matches_result,
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
        return self._with_display_run_timestamps(refreshed_report_output, queryer=tx)

    def ensure_report_output_dual_write_state(
        self,
        report_output_id: int,
        country_id: str | None = None,
    ) -> dict:
        with self.unit_of_work.transaction() as daos:
            return self._ensure_report_output_dual_write_state_in_transaction(
                daos,
                report_output_id,
                country_id=country_id,
            )

    def get_stored_report_output(
        self, country_id: str, report_output_id: int
    ) -> dict | None:
        """
        Get a stored report output row without aliasing to current runtime lineage.

        This is used by mutation paths that must address the originally
        requested row. It still runs dual-write synchronization, so it may
        bootstrap or repair run/spec metadata and returns the display-run
        timestamp projection. It is therefore not a raw storage read.

        TODO: Split raw storage lookup from synchronized response projection in
        a later run-backed read migration PR.
        """
        report_output = self._get_report_output_row(
            report_output_id, country_id=country_id
        )
        if report_output is None:
            return None
        return self.ensure_report_output_dual_write_state(
            report_output_id,
            country_id=country_id,
        )

    def report_output_exists(self, country_id: str, report_output_id: int) -> bool:
        return (
            self._get_report_output_row(report_output_id, country_id=country_id)
            is not None
        )

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
        api_version = get_report_output_cache_version(country_id)
        if queryer is None:
            with self.unit_of_work.read() as daos:
                return self._find_existing_report_output_row(
                    country_id=country_id,
                    simulation_1_id=simulation_1_id,
                    simulation_2_id=simulation_2_id,
                    year=year,
                    queryer=daos,
                )
        return queryer.reports.find_latest(
            country_id=country_id,
            simulation_1_id=simulation_1_id,
            simulation_2_id=simulation_2_id,
            year=year,
            api_version=api_version,
        )

    def _get_or_create_current_report_output(self, report_output: dict) -> dict:
        current_report = self.find_existing_report_output(
            country_id=report_output["country_id"],
            simulation_1_id=report_output["simulation_1_id"],
            simulation_2_id=report_output["simulation_2_id"],
            year=report_output["year"],
        )
        if current_report is not None:
            return self._with_display_run_timestamps(current_report)

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
                return self.ensure_report_output_dual_write_state(
                    existing_report["id"],
                    country_id=country_id,
                )
            return None

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
        """
        print("Creating new report output")
        api_version = get_report_output_cache_version(country_id)

        try:
            with self.unit_of_work.transaction() as daos:
                existing_report = self._find_existing_report_output_row(
                    country_id=country_id,
                    simulation_1_id=simulation_1_id,
                    simulation_2_id=simulation_2_id,
                    year=year,
                    queryer=daos,
                )
                if existing_report is not None:
                    print(
                        f"Reusing existing report output with ID: {existing_report['id']}"
                    )
                    return self._ensure_report_output_dual_write_state_in_transaction(
                        daos,
                        existing_report["id"],
                        country_id=country_id,
                    )

                self._require_simulation_exists(
                    daos,
                    country_id=country_id,
                    simulation_id=simulation_1_id,
                )
                if simulation_2_id is not None:
                    self._require_simulation_exists(
                        daos,
                        country_id=country_id,
                        simulation_id=simulation_2_id,
                    )

                report_output_id = daos.reports.create(
                    country_id=country_id,
                    simulation_1_id=simulation_1_id,
                    simulation_2_id=simulation_2_id,
                    api_version=api_version,
                    status="pending",
                    year=year,
                )
                created_report = daos.reports.get(report_output_id, country_id)
                if created_report is None:
                    raise Exception("Failed to retrieve created report output")

                print(f"Created report output with ID: {created_report['id']}")
                return self._ensure_report_output_dual_write_state_in_transaction(
                    daos,
                    created_report["id"],
                    country_id=country_id,
                )

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
                return self.ensure_report_output_dual_write_state(
                    report_output_id,
                    country_id=country_id,
                )

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
        """
        print(f"Updating report output {report_id}")

        try:
            update_values = {}

            if status is not None:
                update_values["status"] = status

            if output is not None:
                update_values["output"] = parse_json_field(output)

            if error_message is not None:
                update_values["error_message"] = error_message

            if not update_values:
                print("No fields to update")
                return False

            with self.unit_of_work.transaction() as daos:
                requested_report = self._get_report_output_row(
                    report_id,
                    queryer=daos,
                    country_id=country_id,
                    for_update=True,
                )
                if requested_report is None:
                    raise ValueError(f"Report output #{report_id} not found")

                if status == "running" and not self._has_mutable_running_run(
                    requested_report, queryer=daos
                ):
                    raise ValueError(
                        "Cannot mark report output running without an active "
                        "pending or running report run"
                    )

                daos.reports.update(report_id, **update_values)
                self._ensure_report_output_dual_write_state_in_transaction(
                    daos,
                    report_id,
                    country_id=country_id,
                )

            print(f"Successfully updated report output #{report_id}")
            return True

        except Exception as e:
            print(f"Error updating report output #{report_id}. Details: {str(e)}")
            raise e
