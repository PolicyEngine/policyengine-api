import pytest
from sqlalchemy import func, select

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.data.v1_models import (
    ReportOutput,
    ReportOutputRun,
)
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.report_run_service import ReportRunService
from policyengine_api.services.simulation_service import SimulationService


service = ReportOutputService()
run_service = ReportRunService()
simulation_service = SimulationService()


def create_simulation(orm_session, *, policy_id=1, population_id="household-1"):
    return simulation_service._create_simulation(
        orm_session,
        country_id="us",
        population_id=population_id,
        population_type="household",
        policy_id=policy_id,
    )


def test_creates_mapped_report_with_spec_and_initial_run(orm_session):
    simulation = create_simulation(orm_session)

    report = service.create_report_output(
        orm_session,
        country_id="us",
        simulation_1_id=simulation.id,
        year="2025",
    )

    assert isinstance(report, ReportOutput)
    assert report.report_kind == "household_single"
    assert isinstance(report.report_spec_json, dict)
    run = orm_session.get(ReportOutputRun, report.active_run_id)
    assert isinstance(run, ReportOutputRun)
    assert run.status == "pending"
    assert run.report_spec_snapshot_json == report.report_spec_json


def test_create_reuses_current_report_and_repairs_dual_state(orm_session):
    simulation = create_simulation(orm_session)
    existing = ReportOutput(
        country_id="us",
        simulation_1_id=simulation.id,
        simulation_2_id=None,
        api_version=get_report_output_cache_version("us"),
        status="pending",
        year="2025",
    )
    orm_session.add(existing)
    orm_session.flush()

    result = service.create_report_output(orm_session, "us", simulation.id, year="2025")

    assert result is existing
    assert existing.active_run_id is not None
    assert existing.report_spec_json is not None


@pytest.mark.parametrize("missing_secondary", [False, True])
def test_create_rejects_missing_linked_simulation(orm_session, missing_secondary):
    simulation = create_simulation(orm_session) if missing_secondary else None

    with pytest.raises(ValueError, match="references missing simulation"):
        service.create_report_output(
            orm_session,
            "us",
            simulation.id if simulation else 999,
            999 if missing_secondary else None,
        )

    assert orm_session.scalar(select(func.count()).select_from(ReportOutput)) == 0


def test_find_existing_report_uses_current_cache_version(orm_session):
    simulation = create_simulation(orm_session)
    stale = ReportOutput(
        country_id="us",
        simulation_1_id=simulation.id,
        simulation_2_id=None,
        api_version="stale",
        status="pending",
        year="2025",
    )
    orm_session.add(stale)
    orm_session.flush()

    assert (
        service.find_existing_report_output(
            orm_session, "us", simulation.id, year="2025"
        )
        is None
    )

    current = service.create_report_output(
        orm_session, "us", simulation.id, year="2025"
    )
    assert (
        service.find_existing_report_output(
            orm_session, "us", simulation.id, year="2025"
        )
        is current
    )


def test_get_report_is_scoped_to_country_and_validates_id(orm_session):
    simulation = create_simulation(orm_session)
    report = service.create_report_output(orm_session, "us", simulation.id)

    assert service.get_report_output(orm_session, "us", report.id) is report
    assert service.get_report_output(orm_session, "uk", report.id) is None
    with pytest.raises(Exception, match="Invalid report output ID"):
        service.get_report_output(orm_session, "us", -1)


def test_update_complete_stores_python_json_and_promotes_run(orm_session):
    simulation = create_simulation(orm_session)
    report = service.create_report_output(orm_session, "us", simulation.id)
    active_run_id = report.active_run_id

    assert service.update_report_output(
        orm_session,
        "us",
        report.id,
        status="complete",
        output={"ok": True},
    )

    assert report.output == {"ok": True}
    assert report.active_run_id is None
    assert report.latest_successful_run_id == active_run_id
    run = orm_session.get(ReportOutputRun, active_run_id)
    assert run.status == "complete"
    assert run.output == {"ok": True}
    assert run.started_at is not None
    assert run.finished_at is not None


def test_update_accepts_existing_v1_json_string_boundary(orm_session):
    simulation = create_simulation(orm_session)
    report = service.create_report_output(orm_session, "us", simulation.id)

    service.update_report_output(orm_session, "us", report.id, output='{"ok": true}')

    assert report.output == {"ok": True}


def test_update_running_requires_mutable_run(orm_session):
    simulation = create_simulation(orm_session)
    report = service.create_report_output(orm_session, "us", simulation.id)
    service.update_report_output(
        orm_session, "us", report.id, status="complete", output={"ok": True}
    )

    with pytest.raises(ValueError, match="without an active pending or running"):
        service.update_report_output(orm_session, "us", report.id, status="running")


def test_update_running_targets_active_rerun(orm_session):
    simulation = create_simulation(orm_session)
    report = service.create_report_output(orm_session, "us", simulation.id)
    service.update_report_output(
        orm_session, "us", report.id, status="complete", output={"old": True}
    )
    successful_run_id = report.latest_successful_run_id
    rerun = run_service.create_report_output_run(
        orm_session, report.id, trigger_type="rerun"
    )
    report.active_run_id = rerun.id

    service.update_report_output(orm_session, "us", report.id, status="running")

    assert rerun.status == "running"
    assert rerun.started_at is not None
    assert report.active_run_id == rerun.id
    assert report.latest_successful_run_id == successful_run_id


def test_failed_rerun_preserves_latest_successful_pointer(orm_session):
    simulation = create_simulation(orm_session)
    report = service.create_report_output(orm_session, "us", simulation.id)
    service.update_report_output(
        orm_session, "us", report.id, status="complete", output={"old": True}
    )
    successful_run_id = report.latest_successful_run_id
    rerun = run_service.create_report_output_run(
        orm_session, report.id, trigger_type="rerun"
    )
    report.active_run_id = rerun.id

    service.update_report_output(
        orm_session, "us", report.id, status="error", error_message="failed"
    )

    assert report.active_run_id is None
    assert report.latest_successful_run_id == successful_run_id
    assert rerun.status == "error"
    assert rerun.finished_at is not None


def test_noop_and_missing_updates(orm_session):
    simulation = create_simulation(orm_session)
    report = service.create_report_output(orm_session, "us", simulation.id)

    assert service.update_report_output(orm_session, "us", report.id) is False
    with pytest.raises(ValueError, match="Report output #999 not found"):
        service.update_report_output(orm_session, "us", 999, status="pending")
