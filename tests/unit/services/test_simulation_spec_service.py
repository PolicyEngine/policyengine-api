import pytest

from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.services.simulation_spec_service import (
    SimulationSpec,
    SimulationSpecService,
)


simulation_service = SimulationService()
spec_service = SimulationSpecService()


def create_simulation(orm_session):
    return simulation_service.create_simulation(orm_session, "us", "ca", "geography", 3)


def test_builds_spec_from_mapped_simulation(orm_session):
    simulation = create_simulation(orm_session)

    spec = spec_service.build_simulation_spec(simulation)

    assert isinstance(spec, SimulationSpec)
    assert spec.model_dump() == {
        "country_id": "us",
        "population_id": "ca",
        "population_type": "geography",
        "policy_id": 3,
    }


def test_sets_and_gets_python_json_spec(orm_session):
    simulation = create_simulation(orm_session)
    spec = spec_service.build_simulation_spec(simulation)

    assert spec_service.set_simulation_spec(orm_session, simulation.id, spec) is True
    loaded = spec_service.get_simulation_spec(orm_session, simulation.id)

    assert simulation.simulation_spec_json == spec.model_dump()
    assert loaded == spec


def test_rejects_unsupported_schema_version_on_write(orm_session):
    simulation = create_simulation(orm_session)
    spec = spec_service.build_simulation_spec(simulation)

    with pytest.raises(ValueError, match="Unsupported simulation spec schema version"):
        spec_service.set_simulation_spec(
            orm_session, simulation.id, spec, schema_version=2
        )


def test_rejects_unsupported_schema_version_on_read(orm_session):
    simulation = create_simulation(orm_session)
    simulation.simulation_spec_schema_version = 2

    with pytest.raises(ValueError, match="Unsupported simulation spec schema version"):
        spec_service.get_simulation_spec(orm_session, simulation.id)


def test_rejects_spec_that_does_not_match_simulation(orm_session):
    simulation = create_simulation(orm_session)
    mismatched = SimulationSpec(
        country_id="us",
        population_id="ny",
        population_type="geography",
        policy_id=3,
    )

    with pytest.raises(ValueError, match="must match the linked simulation"):
        spec_service.set_simulation_spec(orm_session, simulation.id, mismatched)


def test_rejects_inconsistent_stored_spec(orm_session):
    simulation = create_simulation(orm_session)
    simulation.simulation_spec_json = {
        "country_id": "us",
        "population_id": "ny",
        "population_type": "geography",
        "policy_id": 3,
    }

    with pytest.raises(ValueError, match="must match the linked simulation"):
        spec_service.get_simulation_spec(orm_session, simulation.id)


def test_missing_simulation_has_no_spec(orm_session):
    assert spec_service.get_simulation_spec(orm_session, 999) is None


def test_setting_spec_for_missing_simulation_raises(orm_session):
    spec = SimulationSpec(
        country_id="us",
        population_id="ca",
        population_type="geography",
        policy_id=3,
    )

    with pytest.raises(ValueError, match="Simulation #999 not found"):
        spec_service.set_simulation_spec(orm_session, 999, spec)
