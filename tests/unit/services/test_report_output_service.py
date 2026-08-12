import pytest
from sqlalchemy import func, select

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.data.v1_models import ReportOutput, ReportOutputRun
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.report_run_service import ReportRunService
from policyengine_api.services.simulation_service import SimulationService


run_service = ReportRunService()


@pytest.fixture
def service(orm_session_factory):
    return ReportOutputService(orm_session_factory)


def create_simulation(
    orm_session_factory,
    *,
    policy_id=1,
    population_id="household-1",
):
    return (
        SimulationService(orm_session_factory)
        .get_or_create_simulation(
            country_id="us",
            population_id=population_id,
            population_type="household",
            policy_id=policy_id,
        )
        .simulation
    )


def create_report(service, simulation_id, *, year="2025"):
    return service.create_or_reuse_report_output(
        "us", simulation_id, year=year
    ).view.report_output


def test_creates_mapped_report_with_spec_and_initial_run(
    service,
    orm_session_factory,
):
    simulation = create_simulation(orm_session_factory)

    creation = service.create_or_reuse_report_output(
        country_id="us",
        simulation_1_id=simulation.id,
        year="2025",
    )
    report = creation.view.report_output

    assert creation.created is True
    assert isinstance(report, ReportOutput)
    assert report.report_kind == "household_single"
    assert isinstance(report.report_spec_json, dict)
    assert isinstance(creation.view.display_run, ReportOutputRun)
    assert creation.view.display_run.status == "pending"
    assert (
        creation.view.display_run.report_spec_snapshot_json == report.report_spec_json
    )


def test_create_reuses_current_report_and_repairs_dual_state(
    service,
    orm_session_factory,
):
    simulation = create_simulation(orm_session_factory)
    with orm_session_factory.begin() as session:
        existing = ReportOutput(
            country_id="us",
            simulation_1_id=simulation.id,
            simulation_2_id=None,
            api_version=get_report_output_cache_version("us"),
            status="pending",
            year="2025",
        )
        session.add(existing)
        session.flush()
        report_id = existing.id

    result = service.create_or_reuse_report_output("us", simulation.id, year="2025")

    assert result.created is False
    assert result.view.report_output.id == report_id
    assert result.view.report_output.active_run_id is not None
    assert result.view.report_output.report_spec_json is not None


@pytest.mark.parametrize("missing_secondary", [False, True])
def test_create_rejects_missing_linked_simulation(
    service,
    orm_session_factory,
    missing_secondary,
):
    simulation = create_simulation(orm_session_factory) if missing_secondary else None

    with pytest.raises(ValueError, match="references missing simulation"):
        service.create_or_reuse_report_output(
            "us",
            simulation.id if simulation else 999,
            999 if missing_secondary else None,
        )

    with orm_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ReportOutput)) == 0


def test_create_ignores_stale_cache_version(service, orm_session_factory):
    simulation = create_simulation(orm_session_factory)
    with orm_session_factory.begin() as session:
        stale = ReportOutput(
            country_id="us",
            simulation_1_id=simulation.id,
            simulation_2_id=None,
            api_version="stale",
            status="pending",
            year="2025",
        )
        session.add(stale)
        session.flush()
        stale_id = stale.id

    current = service.create_or_reuse_report_output("us", simulation.id, year="2025")

    assert current.created is True
    assert current.view.report_output.id != stale_id
    assert current.view.report_output.api_version == get_report_output_cache_version(
        "us"
    )


def test_resolve_is_scoped_to_country_and_validates_id(
    service,
    orm_session_factory,
):
    simulation = create_simulation(orm_session_factory)
    report = create_report(service, simulation.id)

    assert service.resolve_report_output("us", report.id).report_output.id == report.id
    assert service.resolve_report_output("uk", report.id) is None
    with pytest.raises(Exception, match="Invalid report output ID"):
        service.resolve_report_output("us", -1)


def test_update_complete_stores_python_json_and_promotes_run(
    service,
    orm_session_factory,
):
    simulation = create_simulation(orm_session_factory)
    report = create_report(service, simulation.id)
    active_run_id = report.active_run_id

    view = service.update_report_output(
        "us",
        report.id,
        status="complete",
        output={"ok": True},
    )

    assert view.report_output.output == {"ok": True}
    assert view.report_output.active_run_id is None
    assert view.report_output.latest_successful_run_id == active_run_id
    assert view.display_run.status == "complete"
    assert view.display_run.output == {"ok": True}
    assert view.display_run.started_at is not None
    assert view.display_run.finished_at is not None


def test_update_accepts_existing_v1_json_string_boundary(
    service,
    orm_session_factory,
):
    simulation = create_simulation(orm_session_factory)
    report = create_report(service, simulation.id)

    view = service.update_report_output("us", report.id, output='{"ok": true}')

    assert view.report_output.output == {"ok": True}


def test_update_running_requires_mutable_run(service, orm_session_factory):
    simulation = create_simulation(orm_session_factory)
    report = create_report(service, simulation.id)
    service.update_report_output(
        "us", report.id, status="complete", output={"ok": True}
    )

    with pytest.raises(ValueError, match="without an active pending or running"):
        service.update_report_output("us", report.id, status="running")


def _add_rerun(orm_session_factory, report_id):
    with orm_session_factory.begin() as session:
        report = session.get(ReportOutput, report_id)
        successful_run_id = report.latest_successful_run_id
        rerun = run_service.create_report_output_run(
            session, report.id, trigger_type="rerun"
        )
        report.active_run_id = rerun.id
        return rerun.id, successful_run_id


def test_update_running_targets_active_rerun(service, orm_session_factory):
    simulation = create_simulation(orm_session_factory)
    report = create_report(service, simulation.id)
    service.update_report_output(
        "us", report.id, status="complete", output={"old": True}
    )
    rerun_id, successful_run_id = _add_rerun(orm_session_factory, report.id)

    view = service.update_report_output("us", report.id, status="running")

    assert view.display_run.id == rerun_id
    assert view.display_run.status == "running"
    assert view.display_run.started_at is not None
    assert view.report_output.active_run_id == rerun_id
    assert view.report_output.latest_successful_run_id == successful_run_id


def test_failed_rerun_preserves_latest_successful_pointer(
    service,
    orm_session_factory,
):
    simulation = create_simulation(orm_session_factory)
    report = create_report(service, simulation.id)
    service.update_report_output(
        "us", report.id, status="complete", output={"old": True}
    )
    rerun_id, successful_run_id = _add_rerun(orm_session_factory, report.id)

    view = service.update_report_output(
        "us", report.id, status="error", error_message="failed"
    )

    assert view.report_output.active_run_id is None
    assert view.report_output.latest_successful_run_id == successful_run_id
    assert view.display_run.id == rerun_id
    assert view.display_run.status == "error"
    assert view.display_run.finished_at is not None


def test_noop_and_missing_updates(service, orm_session_factory):
    simulation = create_simulation(orm_session_factory)
    report = create_report(service, simulation.id)

    assert service.update_report_output("us", report.id) is None
    with pytest.raises(LookupError, match="Report output #999 not found"):
        service.update_report_output("us", 999, status="pending")
