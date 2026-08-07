import pytest

from policyengine_api.data.v1_models import Simulation, SimulationRun
from policyengine_api.services.simulation_service import SimulationService


service = SimulationService()


def test_finds_existing_simulation_without_api_version_matching(orm_session):
    existing = Simulation(
        country_id="us",
        api_version="old-version",
        population_id="household-1",
        population_type="household",
        policy_id=1,
        status="pending",
    )
    orm_session.add(existing)
    orm_session.flush()

    result = service.find_existing_simulation(
        orm_session,
        country_id="us",
        population_id="household-1",
        population_type="household",
        policy_id=1,
    )

    assert result is existing


def test_returns_none_when_simulation_does_not_exist(orm_session):
    assert (
        service.find_existing_simulation(
            orm_session,
            country_id="uk",
            population_id="missing",
            population_type="household",
            policy_id=999,
        )
        is None
    )


def test_creates_mapped_simulation_and_initial_run(orm_session):
    simulation = service.create_simulation(
        orm_session,
        country_id="us",
        population_id="household-1",
        population_type="household",
        policy_id=1,
    )

    assert isinstance(simulation, Simulation)
    assert simulation.simulation_spec_json == {
        "country_id": "us",
        "population_id": "household-1",
        "population_type": "household",
        "policy_id": 1,
    }
    assert simulation.simulation_spec_schema_version == 1
    run = orm_session.get(SimulationRun, simulation.active_run_id)
    assert isinstance(run, SimulationRun)
    assert run.status == "pending"
    assert run.trigger_type == "initial"
    assert run.simulation_spec_snapshot_json == simulation.simulation_spec_json


def test_creation_reuses_existing_row_and_bootstraps_dual_write_state(orm_session):
    existing = Simulation(
        country_id="us",
        api_version="old-version",
        population_id="household-1",
        population_type="household",
        policy_id=7,
        status="pending",
    )
    orm_session.add(existing)
    orm_session.flush()

    result = service.create_simulation(
        orm_session,
        country_id="us",
        population_id="household-1",
        population_type="household",
        policy_id=7,
    )

    assert result is existing
    run = orm_session.get(SimulationRun, existing.active_run_id)
    assert isinstance(run, SimulationRun)
    assert run.simulation_id == existing.id


def test_caller_transaction_rolls_back_creation_on_dual_write_failure(
    orm_session_factory, monkeypatch
):
    def fail_dual_write(*args, **kwargs):
        raise RuntimeError("dual write sync failed")

    monkeypatch.setattr(service, "ensure_simulation_dual_write_state", fail_dual_write)

    with pytest.raises(RuntimeError, match="dual write sync failed"):
        with orm_session_factory.begin() as session:
            service.create_simulation(
                session,
                country_id="us",
                population_id="rollback",
                population_type="household",
                policy_id=8,
            )

    with orm_session_factory() as session:
        assert (
            service.find_existing_simulation(
                session,
                country_id="us",
                population_id="rollback",
                population_type="household",
                policy_id=8,
            )
            is None
        )


def test_get_simulation_returns_model_scoped_to_country(orm_session):
    simulation = service.create_simulation(
        orm_session, "us", "household-1", "household", 1
    )

    assert service.get_simulation(orm_session, "us", simulation.id) is simulation
    assert service.get_simulation(orm_session, "uk", simulation.id) is None


@pytest.mark.parametrize("simulation_id", [-1, "1", None])
def test_get_simulation_rejects_invalid_ids(orm_session, simulation_id):
    with pytest.raises(Exception, match="Invalid simulation ID"):
        service.get_simulation(orm_session, "us", simulation_id)


def test_update_simulation_updates_model_and_run_with_python_json(orm_session):
    simulation = service.create_simulation(
        orm_session, "us", "household-1", "household", 1
    )

    updated = service.update_simulation(
        orm_session,
        "us",
        simulation.id,
        status="complete",
        output={"result": 42},
    )

    assert updated is True
    assert simulation.output == {"result": 42}
    assert simulation.active_run_id is None
    run = orm_session.get(SimulationRun, simulation.latest_successful_run_id)
    assert run.output == {"result": 42}
    assert run.status == "complete"


def test_update_simulation_accepts_json_only_at_existing_wire_boundary(orm_session):
    simulation = service.create_simulation(
        orm_session, "us", "household-1", "household", 1
    )

    service.update_simulation(
        orm_session,
        "us",
        simulation.id,
        output='{"result": 42}',
    )

    assert simulation.output == {"result": 42}


def test_update_simulation_without_values_is_a_noop(orm_session):
    simulation = service.create_simulation(
        orm_session, "us", "household-1", "household", 1
    )

    assert service.update_simulation(orm_session, "us", simulation.id) is False


def test_update_missing_simulation_raises(orm_session):
    with pytest.raises(ValueError, match="Simulation #999 not found"):
        service.update_simulation(orm_session, "us", 999, status="complete")
