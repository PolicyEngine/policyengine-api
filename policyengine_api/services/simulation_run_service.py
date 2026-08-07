import json
import uuid
from typing import Any

from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import SimulationDAO, V1UnitOfWork


SIMULATION_RUN_VERSION_FIELDS = (
    "country_package_version",
    "policyengine_version",
    "data_version",
    "runtime_app_name",
    "simulation_cache_version",
)


class SimulationRunService:
    def __init__(
        self,
        simulations: SimulationDAO | None = None,
        *,
        unit_of_work: V1UnitOfWork | None = None,
    ):
        self._simulations = simulations
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
        if isinstance(run.get("simulation_spec_snapshot_json"), str):
            run["simulation_spec_snapshot_json"] = json.loads(
                run["simulation_spec_snapshot_json"]
            )
        return run

    def create_simulation_run(
        self,
        simulation_id: int,
        report_output_run_id: str | None = None,
        input_position: int | None = None,
        status: str = "pending",
        trigger_type: str = "initial",
        output: dict[str, Any] | list[Any] | str | None = None,
        error_message: str | None = None,
        source_run_id: str | None = None,
        simulation_spec_snapshot: dict[str, Any] | str | None = None,
        version_manifest: dict[str, str | None] | None = None,
        run_id: str | None = None,
    ) -> dict:
        values = {
            "report_output_run_id": report_output_run_id,
            "input_position": input_position,
            "status": status,
            "output": output,
            "error_message": error_message,
            "trigger_type": trigger_type,
            "requested_at": None,
            "started_at": None,
            "finished_at": None,
            "source_run_id": source_run_id,
            "simulation_spec_snapshot_json": simulation_spec_snapshot,
        }
        values.update(
            {
                field: (version_manifest or {}).get(field)
                for field in SIMULATION_RUN_VERSION_FIELDS
            }
        )
        try:
            if self._simulations is not None:
                run = self._simulations.create_run(
                    simulation_id,
                    run_id=run_id or str(uuid.uuid4()),
                    **values,
                )
            else:
                with self.unit_of_work.transaction() as daos:
                    run = daos.simulations.create_run(
                        simulation_id,
                        run_id=run_id or str(uuid.uuid4()),
                        **values,
                    )
        except LookupError as error:
            raise ValueError(f"Simulation #{simulation_id} not found") from error
        return self._parse_run_row(run)

    def get_simulation_run(self, run_id: str) -> dict | None:
        if self._simulations is not None:
            return self._parse_run_row(self._simulations.get_run(run_id))
        with self.unit_of_work.read() as daos:
            return self._parse_run_row(daos.simulations.get_run(run_id))

    def list_simulation_runs(self, simulation_id: int) -> list[dict]:
        if self._simulations is not None:
            rows = self._simulations.list_runs(simulation_id)
        else:
            with self.unit_of_work.read() as daos:
                rows = daos.simulations.list_runs(simulation_id)
        return [self._parse_run_row(row) for row in reversed(rows)]

    def get_newest_simulation_run(self, simulation_id: int) -> dict | None:
        if self._simulations is not None:
            rows = self._simulations.list_runs(simulation_id)
        else:
            with self.unit_of_work.read() as daos:
                rows = daos.simulations.list_runs(simulation_id)
        return self._parse_run_row(rows[0]) if rows else None

    def select_display_run(self, simulation: dict) -> dict | None:
        if simulation.get("active_run_id"):
            active_run = self.get_simulation_run(simulation["active_run_id"])
            if active_run is not None:
                return active_run
        if simulation.get("latest_successful_run_id"):
            successful = self.get_simulation_run(simulation["latest_successful_run_id"])
            if successful is not None:
                return successful
        return self.get_newest_simulation_run(simulation["id"])
