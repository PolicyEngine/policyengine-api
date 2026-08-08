import pytest

from policyengine_api.data.v1_models import SimulationRun
from policyengine_api.services.simulation_run_service import SimulationRunService
from policyengine_api.services.simulation_service import SimulationService


run_service = SimulationRunService()
simulation_service = SimulationService()


def create_simulation(orm_session, population_id="household-1"):
    return simulation_service.create_simulation(
        orm_session, "us", population_id, "household", 1
    )


def test_creates_mapped_runs_with_incrementing_sequence(orm_session):
    simulation = create_simulation(orm_session)

    first = run_service.create_simulation_run(
        orm_session,
        simulation.id,
        input_position=1,
        trigger_type="rerun",
        simulation_spec_snapshot={"population_id": "household-1"},
        version_manifest={"simulation_cache_version": "s123"},
    )
    second = run_service.create_simulation_run(
        orm_session, simulation.id, input_position=1, trigger_type="rerun"
    )

    assert isinstance(first, SimulationRun)
    assert first.run_sequence == 2
    assert first.simulation_spec_snapshot_json == {"population_id": "household-1"}
    assert first.simulation_cache_version == "s123"
    assert second.run_sequence == 3


def test_raises_when_parent_simulation_is_missing(orm_session):
    with pytest.raises(ValueError, match="Simulation #999999 not found"):
        run_service.create_simulation_run(orm_session, 999999)


def test_gets_and_lists_runs_as_models(orm_session):
    simulation = create_simulation(orm_session)
    first = run_service.get_simulation_run(orm_session, simulation.active_run_id)
    second = run_service.create_simulation_run(orm_session, simulation.id)

    assert run_service.get_simulation_run(orm_session, second.id) is second
    assert run_service.list_simulation_runs(orm_session, simulation.id) == [
        first,
        second,
    ]
    assert run_service.get_newest_simulation_run(orm_session, simulation.id) is second


def test_display_run_prefers_active_run(orm_session):
    simulation = create_simulation(orm_session)
    successful = run_service.create_simulation_run(
        orm_session, simulation.id, status="complete"
    )
    active = run_service.create_simulation_run(
        orm_session, simulation.id, status="running"
    )
    simulation.latest_successful_run_id = successful.id
    simulation.active_run_id = active.id

    assert run_service.select_display_run(orm_session, simulation) is active


def test_display_run_falls_back_to_latest_successful_run(orm_session):
    simulation = create_simulation(orm_session)
    successful = run_service.create_simulation_run(
        orm_session, simulation.id, status="complete"
    )
    run_service.create_simulation_run(orm_session, simulation.id)
    simulation.active_run_id = None
    simulation.latest_successful_run_id = successful.id

    assert run_service.select_display_run(orm_session, simulation) is successful


def test_display_run_falls_back_to_newest_for_stale_pointers(orm_session):
    simulation = create_simulation(orm_session)
    newest = run_service.create_simulation_run(orm_session, simulation.id)
    simulation.active_run_id = "missing-active-run"
    simulation.latest_successful_run_id = "missing-successful-run"

    assert run_service.select_display_run(orm_session, simulation) is newest
