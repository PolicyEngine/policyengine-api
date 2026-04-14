import json
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.engine.row import Row

from policyengine_api.data import database

SIMULATION_SPEC_SCHEMA_VERSION = 1


class SimulationSpec(BaseModel):
    country_id: str
    population_id: str
    population_type: Literal["household", "geography"]
    policy_id: int


class SimulationSpecService:
    def _get_simulation_row(self, simulation_id: int) -> dict | None:
        row: Row | None = database.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def build_simulation_spec(self, simulation: dict) -> SimulationSpec:
        return SimulationSpec.model_validate(
            {
                "country_id": simulation["country_id"],
                "population_id": simulation["population_id"],
                "population_type": simulation["population_type"],
                "policy_id": simulation["policy_id"],
            }
        )

    def get_simulation_spec(self, simulation_id: int) -> SimulationSpec | None:
        simulation = self._get_simulation_row(simulation_id)
        if simulation is None or simulation["simulation_spec_json"] is None:
            return None

        raw_spec = simulation["simulation_spec_json"]
        if isinstance(raw_spec, str):
            raw_spec = json.loads(raw_spec)
        return SimulationSpec.model_validate(raw_spec)

    def set_simulation_spec(
        self,
        simulation_id: int,
        simulation_spec: SimulationSpec,
        schema_version: int = SIMULATION_SPEC_SCHEMA_VERSION,
    ) -> bool:
        simulation = self._get_simulation_row(simulation_id)
        if simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found")

        database.query(
            """
            UPDATE simulations
            SET simulation_spec_json = ?, simulation_spec_schema_version = ?
            WHERE id = ?
            """,
            (
                simulation_spec.model_dump_json(),
                schema_version,
                simulation_id,
            ),
        )
        return True
