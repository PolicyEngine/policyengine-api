from datetime import datetime

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import V1UnitOfWork
from tests.unit.data.sqlite_schema import create_sqlite_v1_schema


def _unit_of_work():
    manager = build_sqlite_session_manager()
    create_sqlite_v1_schema(manager)
    return V1UnitOfWork(manager)


def test_simulation_dao_creates_parent_and_monotonic_runs_atomically():
    uow = _unit_of_work()
    with uow.transaction() as repositories:
        simulation_id = repositories.simulations.create(
            country_id="us",
            api_version="1",
            population_id="7",
            population_type="household",
            policy_id=2,
        )
        first = repositories.simulations.create_run(
            simulation_id,
            run_id="run-1",
            status="pending",
            trigger_type="create",
            requested_at=datetime(2026, 1, 1),
        )
        second = repositories.simulations.create_run(
            simulation_id,
            run_id="run-2",
            status="pending",
            trigger_type="retry",
            requested_at=datetime(2026, 1, 2),
        )
    with uow.read() as repositories:
        assert first["run_sequence"] == 1
        assert second["run_sequence"] == 2
        assert repositories.simulations.list_runs(simulation_id)[0]["id"] == "run-2"


def test_report_dao_round_trips_parent_run_and_alias():
    uow = _unit_of_work()
    with uow.transaction() as repositories:
        report_id = repositories.reports.create(
            country_id="us",
            simulation_1_id=1,
            simulation_2_id=None,
            api_version="1",
            year="2026",
        )
        run = repositories.reports.create_run(
            report_id,
            run_id="report-run",
            status="pending",
            trigger_type="create",
            requested_at=datetime(2026, 1, 1),
        )
        repositories.reports.set_alias(99, report_id)
    with uow.read() as repositories:
        assert repositories.reports.get(report_id)["status"] == "pending"
        assert run["run_sequence"] == 1
        assert (
            repositories.reports.get_alias(99)["canonical_report_output_id"]
            == report_id
        )
