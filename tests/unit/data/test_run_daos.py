from datetime import datetime

import pytest

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import SimulationDAO, V1UnitOfWork
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


def test_simulation_dao_sync_callbacks_cover_create_update_and_missing_rows():
    uow = _unit_of_work()

    def read_synced(session, simulation_id, *, country_id):
        return SimulationDAO.get_in_session(session, simulation_id, country_id)

    with uow.transaction() as repositories:
        created = repositories.simulations.create_or_get_with_sync(
            sync_callback=read_synced,
            country_id="us",
            api_version="1",
            population_id="7",
            population_type="household",
            policy_id=2,
            status="complete",
            output={"result": 1},
        )
        reused = repositories.simulations.create_or_get_with_sync(
            sync_callback=read_synced,
            country_id="us",
            api_version="1",
            population_id="7",
            population_type="household",
            policy_id=2,
            status="pending",
        )
        updated = repositories.simulations.update_with_sync(
            created["id"],
            "us",
            {"error_message": "updated"},
            read_synced,
        )
        dual_write = repositories.simulations.ensure_dual_write_state(
            created["id"], "us"
        )

        assert reused["id"] == created["id"]
        assert updated["error_message"] == "updated"
        assert dual_write["latest_successful_run_id"] is not None
        assert repositories.simulations.get(created["id"], "uk") is None
        assert repositories.simulations.update(999, status="complete") is False
        with pytest.raises(ValueError, match="Simulation #999 not found"):
            repositories.simulations.update_with_sync(
                999, "us", {"status": "complete"}, read_synced
            )
        with pytest.raises(LookupError, match="Simulation 999 does not exist"):
            repositories.simulations.create_run(
                999,
                run_id="missing-run",
                status="pending",
                trigger_type="create",
            )


def test_report_dao_handles_scoped_lookups_updates_and_existing_aliases():
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
        )

        assert repositories.reports.get(report_id, "uk") is None
        assert repositories.reports.get_for_update(report_id, "us")["id"] == report_id
        assert repositories.reports.get_for_update(report_id, "uk") is None
        assert repositories.reports.update(999, status="complete") is False
        assert repositories.reports.update(report_id, status="complete")
        assert repositories.reports.update_run(
            run["id"], status="complete", output={"result": 1}
        )
        assert repositories.reports.update_run("missing-run", status="error") is False
        repositories.reports.set_alias(99, report_id)
        repositories.reports.set_alias(99, report_id + 1)
        with pytest.raises(LookupError, match="Report output 999 does not exist"):
            repositories.reports.create_run(
                999,
                run_id="missing-run",
                status="pending",
                trigger_type="create",
            )

    with uow.read() as repositories:
        assert repositories.reports.get(report_id)["status"] == "complete"
        assert repositories.reports.get_run(run["id"])["output"] == {"result": 1}
        assert repositories.reports.get_run("missing-run") is None
        assert repositories.reports.get_alias(99)["canonical_report_output_id"] == 2
