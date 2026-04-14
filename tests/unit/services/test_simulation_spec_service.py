from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.services.simulation_spec_service import (
    SimulationSpec,
    SimulationSpecService,
)

simulation_service = SimulationService()
simulation_spec_service = SimulationSpecService()


class TestSimulationSpecService:
    def test_builds_simulation_spec_from_row(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="uk",
            population_id="household_42",
            population_type="household",
            policy_id=7,
        )

        simulation_spec = simulation_spec_service.build_simulation_spec(simulation)

        assert isinstance(simulation_spec, SimulationSpec)
        assert simulation_spec.country_id == "uk"
        assert simulation_spec.population_id == "household_42"
        assert simulation_spec.policy_id == 7

    def test_sets_and_gets_simulation_spec(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="ca",
            population_type="geography",
            policy_id=3,
        )
        simulation_spec = SimulationSpec.model_validate(
            {
                "country_id": "us",
                "population_id": "ca",
                "population_type": "geography",
                "policy_id": 3,
            }
        )

        result = simulation_spec_service.set_simulation_spec(
            simulation["id"], simulation_spec
        )

        assert result is True
        stored_simulation = test_db.query(
            """
            SELECT simulation_spec_json, simulation_spec_schema_version
            FROM simulations WHERE id = ?
            """,
            (simulation["id"],),
        ).fetchone()
        assert stored_simulation["simulation_spec_schema_version"] == 1

        loaded_simulation_spec = simulation_spec_service.get_simulation_spec(
            simulation["id"]
        )
        assert loaded_simulation_spec is not None
        assert loaded_simulation_spec.model_dump() == simulation_spec.model_dump()
