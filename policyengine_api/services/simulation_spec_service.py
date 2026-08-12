import json
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import Simulation

SIMULATION_SPEC_SCHEMA_VERSION = 1


class SimulationSpec(BaseModel):
    country_id: str
    population_id: str
    population_type: Literal["household", "geography"]
    policy_id: int


class SimulationSpecService:
    def _validate_schema_version(self, schema_version: int | None) -> None:
        if schema_version != SIMULATION_SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported simulation spec schema version: {schema_version}"
            )

    def _validate_simulation_spec_matches_model(
        self,
        simulation: Simulation,
        simulation_spec: SimulationSpec,
    ) -> None:
        expected_spec = {
            "country_id": simulation.country_id,
            "population_id": simulation.population_id,
            "population_type": simulation.population_type,
            "policy_id": simulation.policy_id,
        }
        if simulation_spec.model_dump() != expected_spec:
            raise ValueError("Simulation spec must match the linked simulation row")

    def build_simulation_spec(self, simulation: Simulation) -> SimulationSpec:
        return SimulationSpec(
            country_id=simulation.country_id,
            population_id=simulation.population_id,
            population_type=simulation.population_type,
            policy_id=simulation.policy_id,
        )

    def get_simulation_spec(
        self,
        session: Session,
        simulation_id: int,
    ) -> SimulationSpec | None:
        simulation = session.get(Simulation, simulation_id)
        if simulation is None or simulation.simulation_spec_json is None:
            return None

        self._validate_schema_version(simulation.simulation_spec_schema_version)
        raw_spec = simulation.simulation_spec_json
        if isinstance(raw_spec, str):
            # Existing databases may contain pre-ORM JSON text. New writes below
            # always assign Python objects and leave conversion to SQLAlchemy.
            raw_spec = json.loads(raw_spec)
        simulation_spec = SimulationSpec.model_validate(raw_spec)
        self._validate_simulation_spec_matches_model(simulation, simulation_spec)
        return simulation_spec

    def set_simulation_spec(
        self,
        session: Session,
        simulation_id: int,
        simulation_spec: SimulationSpec,
        schema_version: int = SIMULATION_SPEC_SCHEMA_VERSION,
    ) -> bool:
        self._validate_schema_version(schema_version)
        simulation = session.get(Simulation, simulation_id)
        if simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found")
        self._validate_simulation_spec_matches_model(simulation, simulation_spec)
        simulation.simulation_spec_json = simulation_spec.model_dump()
        simulation.simulation_spec_schema_version = schema_version
        return True
