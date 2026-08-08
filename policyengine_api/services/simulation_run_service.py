import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import Simulation, SimulationRun


SIMULATION_RUN_VERSION_FIELDS = (
    "country_package_version",
    "policyengine_version",
    "data_version",
    "runtime_app_name",
    "simulation_cache_version",
)


class SimulationRunService:
    def create_simulation_run(
        self,
        session: Session,
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
    ) -> SimulationRun:
        parent = session.scalar(
            select(Simulation).where(Simulation.id == simulation_id).with_for_update()
        )
        if parent is None:
            raise ValueError(f"Simulation #{simulation_id} not found")
        sequence = (
            session.scalar(
                select(func.max(SimulationRun.run_sequence)).where(
                    SimulationRun.simulation_id == simulation_id
                )
            )
            or 0
        ) + 1
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
        run = SimulationRun(
            id=run_id or str(uuid.uuid4()),
            simulation_id=simulation_id,
            run_sequence=sequence,
            **values,
        )
        session.add(run)
        session.flush()
        return run

    def get_simulation_run(
        self,
        session: Session,
        run_id: str,
    ) -> SimulationRun | None:
        return session.get(SimulationRun, run_id)

    def list_simulation_runs(
        self,
        session: Session,
        simulation_id: int,
    ) -> list[SimulationRun]:
        return list(
            session.scalars(
                select(SimulationRun)
                .where(SimulationRun.simulation_id == simulation_id)
                .order_by(SimulationRun.run_sequence.asc())
            )
        )

    def get_newest_simulation_run(
        self,
        session: Session,
        simulation_id: int,
    ) -> SimulationRun | None:
        return session.scalar(
            select(SimulationRun)
            .where(SimulationRun.simulation_id == simulation_id)
            .order_by(SimulationRun.run_sequence.desc())
        )

    def select_display_run(
        self,
        session: Session,
        simulation: Simulation,
    ) -> SimulationRun | None:
        if simulation.active_run_id:
            active_run = self.get_simulation_run(session, simulation.active_run_id)
            if active_run is not None:
                return active_run
        if simulation.latest_successful_run_id:
            successful = self.get_simulation_run(
                session,
                simulation.latest_successful_run_id,
            )
            if successful is not None:
                return successful
        return self.get_newest_simulation_run(session, simulation.id)
