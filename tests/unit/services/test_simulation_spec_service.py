import pytest

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

    def test_rejects_unsupported_schema_version_on_write(self, test_db):
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

        with pytest.raises(ValueError) as exc_info:
            simulation_spec_service.set_simulation_spec(
                simulation["id"],
                simulation_spec,
                schema_version=2,
            )

        assert "Unsupported simulation spec schema version" in str(exc_info.value)

    def test_rejects_unsupported_schema_version_on_read(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="ca",
            population_type="geography",
            policy_id=3,
        )
        test_db.query(
            """
            UPDATE simulations
            SET simulation_spec_json = ?, simulation_spec_schema_version = ?
            WHERE id = ?
            """,
            (
                '{"country_id":"us","population_id":"ca","population_type":"geography","policy_id":3}',
                2,
                simulation["id"],
            ),
        )

        with pytest.raises(ValueError) as exc_info:
            simulation_spec_service.get_simulation_spec(simulation["id"])

        assert "Unsupported simulation spec schema version" in str(exc_info.value)

    def test_rejects_simulation_spec_write_when_fields_do_not_match_row(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="ca",
            population_type="geography",
            policy_id=3,
        )
        simulation_spec = SimulationSpec.model_validate(
            {
                "country_id": "us",
                "population_id": "ny",
                "population_type": "geography",
                "policy_id": 3,
            }
        )

        with pytest.raises(ValueError) as exc_info:
            simulation_spec_service.set_simulation_spec(
                simulation["id"], simulation_spec
            )

        assert "Simulation spec must match the linked simulation row" in str(
            exc_info.value
        )

    def test_rejects_inconsistent_stored_simulation_spec_on_read(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="ca",
            population_type="geography",
            policy_id=3,
        )
        test_db.query(
            """
            UPDATE simulations
            SET simulation_spec_json = ?, simulation_spec_schema_version = ?
            WHERE id = ?
            """,
            (
                '{"country_id":"us","population_id":"ny","population_type":"geography","policy_id":3}',
                1,
                simulation["id"],
            ),
        )

        with pytest.raises(ValueError) as exc_info:
            simulation_spec_service.get_simulation_spec(simulation["id"])

        assert "Simulation spec must match the linked simulation row" in str(
            exc_info.value
        )
