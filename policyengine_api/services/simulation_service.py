import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Simulation, SimulationRun


@dataclass(frozen=True)
class SimulationCreateResult:
    simulation: Simulation
    created: bool


class SimulationService:
    """Simulation operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    @staticmethod
    def _select_simulation(
        session: Session,
        simulation_id: int,
        country_id: str | None = None,
        *,
        for_update: bool = False,
    ) -> Simulation | None:
        statement = select(Simulation).where(Simulation.id == simulation_id)
        if country_id is not None:
            statement = statement.where(Simulation.country_id == country_id)
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def _latest_successful_run_id(runs: list[SimulationRun]) -> str | None:
        return next((run.id for run in runs if run.status == "complete"), None)

    def _ensure_simulation_dual_write_state(
        self,
        session: Session,
        simulation_id: int,
        country_id: str | None = None,
    ) -> Simulation:
        simulation = self._select_simulation(
            session,
            simulation_id,
            country_id,
            for_update=True,
        )
        if simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found")

        spec = {
            "country_id": simulation.country_id,
            "population_id": simulation.population_id,
            "population_type": simulation.population_type,
            "policy_id": simulation.policy_id,
        }
        simulation.simulation_spec_json = spec
        simulation.simulation_spec_schema_version = 1
        runs = list(
            session.scalars(
                select(SimulationRun)
                .where(SimulationRun.simulation_id == simulation_id)
                .order_by(SimulationRun.run_sequence.desc())
            )
        )
        if not runs:
            run = SimulationRun(
                id=str(uuid.uuid4()),
                simulation_id=simulation_id,
                run_sequence=1,
                status=simulation.status,
                output=simulation.output,
                error_message=simulation.error_message,
                trigger_type="initial",
                simulation_spec_snapshot_json=spec,
                country_package_version=simulation.api_version,
            )
            session.add(run)
            session.flush()
            runs = [run]
        else:
            mutable = next(
                (run for run in runs if run.id == simulation.active_run_id),
                runs[0],
            )
            mutable.status = simulation.status
            mutable.output = simulation.output
            mutable.error_message = simulation.error_message
            mutable.simulation_spec_snapshot_json = spec
            mutable.country_package_version = simulation.api_version

        latest_successful = self._latest_successful_run_id(runs)
        simulation.active_run_id = (
            runs[0].id if simulation.status in {"pending", "running"} else None
        )
        if simulation.status == "complete" and latest_successful is None:
            latest_successful = runs[0].id
        simulation.latest_successful_run_id = latest_successful
        session.flush()
        return simulation

    @staticmethod
    def _find_existing_simulation(
        session: Session,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
        *,
        for_update: bool = False,
    ) -> Simulation | None:
        statement = (
            select(Simulation)
            .where(
                Simulation.country_id == country_id,
                Simulation.population_id == population_id,
                Simulation.population_type == population_type,
                Simulation.policy_id == policy_id,
            )
            .order_by(Simulation.id.desc())
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    def _create_simulation(
        self,
        session: Session,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> Simulation:
        simulation = Simulation(
            country_id=country_id,
            api_version=COUNTRY_PACKAGE_VERSIONS.get(country_id),
            population_id=population_id,
            population_type=population_type,
            policy_id=policy_id,
            status="pending",
        )
        session.add(simulation)
        session.flush()
        return self._ensure_simulation_dual_write_state(
            session,
            simulation.id,
            country_id,
        )

    def get_or_create_simulation(
        self,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> SimulationCreateResult:
        with self._sessions.begin() as session:
            simulation = self._find_existing_simulation(
                session,
                country_id,
                population_id,
                population_type,
                policy_id,
                for_update=True,
            )
            created = simulation is None
            if simulation is None:
                simulation = self._create_simulation(
                    session,
                    country_id,
                    population_id,
                    population_type,
                    policy_id,
                )
            else:
                simulation = self._ensure_simulation_dual_write_state(
                    session,
                    simulation.id,
                    country_id,
                )
            return SimulationCreateResult(simulation=simulation, created=created)

    def get_simulation(
        self,
        country_id: str,
        simulation_id: int,
    ) -> Simulation | None:
        if type(simulation_id) is not int or simulation_id < 0:
            raise Exception(
                f"Invalid simulation ID: {simulation_id}. Must be a positive integer."
            )
        with self._sessions() as session:
            return self._select_simulation(session, simulation_id, country_id)

    def update_simulation(
        self,
        country_id: str,
        simulation_id: int,
        status: str | None = None,
        output: dict | list | str | None = None,
        error_message: str | None = None,
    ) -> Simulation | None:
        values = {
            key: value
            for key, value in {
                "status": status,
                "output": output,
                "error_message": error_message,
            }.items()
            if value is not None
        }
        if not values:
            return None
        if isinstance(values.get("output"), str):
            values["output"] = json.loads(values["output"])
        with self._sessions.begin() as session:
            simulation = self._select_simulation(
                session,
                simulation_id,
                country_id,
                for_update=True,
            )
            if simulation is None:
                raise LookupError(f"Simulation #{simulation_id} not found")
            for key, value in values.items():
                setattr(simulation, key, value)
            simulation.api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)
            return self._ensure_simulation_dual_write_state(
                session,
                simulation_id,
                country_id,
            )
