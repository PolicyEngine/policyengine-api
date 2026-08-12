import inspect

import pytest
from sqlalchemy import func, select

from policyengine_api.data.v1_models import Simulation, SimulationRun
from policyengine_api.services.simulation_service import (
    SimulationCreateResult,
    SimulationService,
)


@pytest.fixture
def service(orm_session_factory):
    return SimulationService(orm_session_factory)


def test_public_simulation_methods_do_not_accept_sessions():
    for method_name in (
        "get_or_create_simulation",
        "get_simulation",
        "update_simulation",
    ):
        parameters = inspect.signature(
            getattr(SimulationService, method_name)
        ).parameters
        assert "session" not in parameters
        assert "session_factory" not in parameters


def test_get_or_create_builds_simulation_spec_and_initial_run(service):
    result = service.get_or_create_simulation(
        country_id="us",
        population_id="household-1",
        population_type="household",
        policy_id=1,
    )

    assert isinstance(result, SimulationCreateResult)
    assert result.created is True
    assert isinstance(result.simulation, Simulation)
    assert result.simulation.simulation_spec_json == {
        "country_id": "us",
        "population_id": "household-1",
        "population_type": "household",
        "policy_id": 1,
    }
    assert result.simulation.simulation_spec_schema_version == 1
    assert result.simulation.active_run_id is not None


def test_get_or_create_reuses_existing_row_and_repairs_dual_write_state(
    service,
    orm_session_factory,
):
    with orm_session_factory.begin() as session:
        existing = Simulation(
            country_id="us",
            api_version="old-version",
            population_id="household-1",
            population_type="household",
            policy_id=7,
            status="pending",
        )
        session.add(existing)
        session.flush()
        simulation_id = existing.id

    result = service.get_or_create_simulation(
        country_id="us",
        population_id="household-1",
        population_type="household",
        policy_id=7,
    )

    assert result.created is False
    assert result.simulation.id == simulation_id
    with orm_session_factory() as session:
        stored = session.get(Simulation, simulation_id)
        run = session.get(SimulationRun, stored.active_run_id)
        assert isinstance(run, SimulationRun)
        assert run.simulation_id == simulation_id


def test_get_or_create_rolls_back_simulation_when_dual_write_fails(
    service,
    orm_session_factory,
    monkeypatch,
):
    def fail_dual_write(*args, **kwargs):
        raise RuntimeError("dual write sync failed")

    monkeypatch.setattr(service, "_ensure_simulation_dual_write_state", fail_dual_write)

    with pytest.raises(RuntimeError, match="dual write sync failed"):
        service.get_or_create_simulation(
            country_id="us",
            population_id="rollback",
            population_type="household",
            policy_id=8,
        )

    with orm_session_factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Simulation)
            .where(Simulation.population_id == "rollback")
        )
    assert count == 0


def test_get_simulation_returns_model_scoped_to_country(service):
    simulation = service.get_or_create_simulation(
        "us", "household-1", "household", 1
    ).simulation

    assert service.get_simulation("us", simulation.id).id == simulation.id
    assert service.get_simulation("uk", simulation.id) is None


@pytest.mark.parametrize("simulation_id", [-1, "1", None])
def test_get_simulation_rejects_invalid_ids(service, simulation_id):
    with pytest.raises(Exception, match="Invalid simulation ID"):
        service.get_simulation("us", simulation_id)


def test_update_simulation_updates_model_and_run_with_python_json(
    service,
    orm_session_factory,
):
    simulation = service.get_or_create_simulation(
        "us", "household-1", "household", 1
    ).simulation

    updated = service.update_simulation(
        "us",
        simulation.id,
        status="complete",
        output={"result": 42},
    )

    assert isinstance(updated, Simulation)
    assert updated.output == {"result": 42}
    assert updated.active_run_id is None
    with orm_session_factory() as session:
        run = session.get(SimulationRun, updated.latest_successful_run_id)
        assert run.output == {"result": 42}
        assert run.status == "complete"


def test_update_simulation_accepts_legacy_json_text_at_wire_boundary(service):
    simulation = service.get_or_create_simulation(
        "us", "household-1", "household", 1
    ).simulation

    updated = service.update_simulation(
        "us",
        simulation.id,
        output='{"result": 42}',
    )

    assert updated.output == {"result": 42}


def test_update_simulation_without_values_is_a_noop(service):
    simulation = service.get_or_create_simulation(
        "us", "household-1", "household", 1
    ).simulation

    assert service.update_simulation("us", simulation.id) is None


def test_update_missing_simulation_raises(service):
    with pytest.raises(LookupError, match="Simulation #999 not found"):
        service.update_simulation("us", 999, status="complete")
