import json

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import SimulationDAO
from policyengine_api.services.simulation_spec_service import SimulationSpecService


class SimulationService:
    def __init__(self, simulations: SimulationDAO | None = None):
        self._simulations = simulations
        self.simulation_spec_service = SimulationSpecService(simulations)

    @property
    def simulations(self) -> SimulationDAO:
        if self._simulations is None:
            self._simulations = SimulationDAO(build_v1_session_manager())
            self.simulation_spec_service = SimulationSpecService(self._simulations)
        return self._simulations

    def _ensure_simulation_dual_write_state_in_transaction(
        self,
        session,
        simulation_id: int,
        *,
        country_id: str | None = None,
    ) -> dict:
        session = getattr(session, "session", session)
        return self.simulations.ensure_dual_write_state_in_session(
            session, simulation_id, country_id
        )

    def _get_simulation_row(
        self,
        simulation_id: int,
        *,
        queryer=None,
        country_id: str | None = None,
        for_update: bool = False,
    ) -> dict | None:
        del for_update
        if queryer is not None and getattr(queryer, "session", None) is not None:
            return self.simulations.get_in_session(
                queryer.session, simulation_id, country_id
            )
        return self.simulations.get(simulation_id, country_id)

    def ensure_simulation_dual_write_state(
        self, simulation_id: int, country_id: str | None = None
    ) -> dict:
        return self.simulations.ensure_dual_write_state(simulation_id, country_id)

    def find_existing_simulation(
        self,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> dict | None:
        return self.simulations.find_latest(
            country_id=country_id,
            population_id=population_id,
            population_type=population_type,
            policy_id=policy_id,
        )

    def create_simulation(
        self,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> dict:
        return self.simulations.create_or_get_with_sync(
            sync_callback=self._ensure_simulation_dual_write_state_in_transaction,
            country_id=country_id,
            api_version=COUNTRY_PACKAGE_VERSIONS.get(country_id),
            population_id=population_id,
            population_type=population_type,
            policy_id=policy_id,
            status="pending",
        )

    def get_simulation(self, country_id: str, simulation_id: int) -> dict | None:
        if type(simulation_id) is not int or simulation_id < 0:
            raise Exception(
                f"Invalid simulation ID: {simulation_id}. Must be a positive integer."
            )
        return self.simulations.get(simulation_id, country_id)

    def update_simulation(
        self,
        country_id: str,
        simulation_id: int,
        status: str | None = None,
        output: str | None = None,
        error_message: str | None = None,
    ) -> bool:
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
            return False
        if isinstance(values.get("output"), str):
            values["output"] = json.loads(values["output"])
        values["api_version"] = COUNTRY_PACKAGE_VERSIONS.get(country_id)
        self.simulations.update_with_sync(
            simulation_id,
            country_id,
            values,
            self._ensure_simulation_dual_write_state_in_transaction,
        )
        return True
