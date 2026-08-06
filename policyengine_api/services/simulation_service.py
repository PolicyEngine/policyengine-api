import json

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import SimulationDAO, V1UnitOfWork
from policyengine_api.services.simulation_spec_service import SimulationSpecService


class SimulationService:
    def __init__(
        self,
        simulations: SimulationDAO | None = None,
        *,
        unit_of_work: V1UnitOfWork | None = None,
    ):
        self._simulations = simulations
        self._unit_of_work = unit_of_work
        self.simulation_spec_service = SimulationSpecService(
            simulations,
            unit_of_work=unit_of_work,
        )

    @property
    def unit_of_work(self) -> V1UnitOfWork:
        if self._unit_of_work is None:
            self._unit_of_work = V1UnitOfWork(build_v1_session_manager())
            self.simulation_spec_service = SimulationSpecService(
                unit_of_work=self._unit_of_work
            )
        return self._unit_of_work

    def _ensure_simulation_dual_write_state_in_transaction(
        self,
        session,
        simulation_id: int,
        *,
        country_id: str | None = None,
    ) -> dict:
        return SimulationDAO(session).ensure_dual_write_state_in_session(
            session,
            simulation_id,
            country_id,
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
        if queryer is not None:
            simulations = getattr(queryer, "simulations", None)
            if simulations is None:
                simulations = SimulationDAO(getattr(queryer, "session", queryer))
            return simulations.get(simulation_id, country_id)
        if self._simulations is not None:
            return self._simulations.get(simulation_id, country_id)
        with self.unit_of_work.read() as repositories:
            return repositories.simulations.get(simulation_id, country_id)

    def ensure_simulation_dual_write_state(
        self, simulation_id: int, country_id: str | None = None
    ) -> dict:
        if self._simulations is not None:
            return self._simulations.ensure_dual_write_state(simulation_id, country_id)
        with self.unit_of_work.transaction() as repositories:
            return repositories.simulations.ensure_dual_write_state(
                simulation_id, country_id
            )

    def find_existing_simulation(
        self,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> dict | None:
        if self._simulations is not None:
            return self._simulations.find_latest(
                country_id=country_id,
                population_id=population_id,
                population_type=population_type,
                policy_id=policy_id,
            )
        with self.unit_of_work.read() as repositories:
            return repositories.simulations.find_latest(
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
        values = {
            "country_id": country_id,
            "api_version": COUNTRY_PACKAGE_VERSIONS.get(country_id),
            "population_id": population_id,
            "population_type": population_type,
            "policy_id": policy_id,
            "status": "pending",
        }
        if self._simulations is not None:
            return self._simulations.create_or_get_with_sync(
                sync_callback=self._ensure_simulation_dual_write_state_in_transaction,
                **values,
            )
        with self.unit_of_work.transaction() as repositories:
            return repositories.simulations.create_or_get_with_sync(
                sync_callback=self._ensure_simulation_dual_write_state_in_transaction,
                **values,
            )

    def get_simulation(self, country_id: str, simulation_id: int) -> dict | None:
        if type(simulation_id) is not int or simulation_id < 0:
            raise Exception(
                f"Invalid simulation ID: {simulation_id}. Must be a positive integer."
            )
        return self._get_simulation_row(simulation_id, country_id=country_id)

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
        if self._simulations is not None:
            self._simulations.update_with_sync(
                simulation_id,
                country_id,
                values,
                self._ensure_simulation_dual_write_state_in_transaction,
            )
        else:
            with self.unit_of_work.transaction() as repositories:
                repositories.simulations.update_with_sync(
                    simulation_id,
                    country_id,
                    values,
                    self._ensure_simulation_dual_write_state_in_transaction,
                )
        return True
