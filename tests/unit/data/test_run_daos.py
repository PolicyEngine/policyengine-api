from datetime import datetime

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import ReportDAO, SimulationDAO
from policyengine_api.data.v1_models import V1Base


def _daos():
    manager = build_sqlite_session_manager()
    V1Base.metadata.create_all(manager.engine)
    return SimulationDAO(manager), ReportDAO(manager)


def test_simulation_dao_creates_parent_and_monotonic_runs_atomically():
    simulations, _ = _daos()
    simulation_id = simulations.create(
        country_id="us",
        api_version="1",
        population_id="7",
        population_type="household",
        policy_id=2,
    )
    first = simulations.create_run(
        simulation_id,
        run_id="run-1",
        status="pending",
        trigger_type="create",
        requested_at=datetime(2026, 1, 1),
    )
    second = simulations.create_run(
        simulation_id,
        run_id="run-2",
        status="pending",
        trigger_type="retry",
        requested_at=datetime(2026, 1, 2),
    )
    assert first["run_sequence"] == 1
    assert second["run_sequence"] == 2
    assert simulations.list_runs(simulation_id)[0]["id"] == "run-2"


def test_report_dao_round_trips_parent_run_and_alias():
    _, reports = _daos()
    report_id = reports.create(
        country_id="us",
        simulation_1_id=1,
        simulation_2_id=None,
        api_version="1",
        year="2026",
    )
    run = reports.create_run(
        report_id,
        run_id="report-run",
        status="pending",
        trigger_type="create",
        requested_at=datetime(2026, 1, 1),
    )
    reports.set_alias(99, report_id)
    assert reports.get(report_id)["status"] == "pending"
    assert run["run_sequence"] == 1
    assert reports.get_alias(99)["canonical_report_output_id"] == report_id
