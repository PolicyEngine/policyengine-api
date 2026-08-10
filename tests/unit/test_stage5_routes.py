import json
from datetime import datetime

from flask import Flask

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.data.v1_models import ReportOutput, ReportOutputRun, Simulation
from policyengine_api.routes.report_output_routes import report_output_bp
from policyengine_api.routes.simulation_routes import simulation_bp
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.report_run_service import ReportRunService
from policyengine_api.services.simulation_service import SimulationService


simulation_service = SimulationService()
report_service = ReportOutputService()
run_service = ReportRunService()


def create_test_client() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(simulation_bp)
    app.register_blueprint(report_output_bp)
    return app.test_client()


def create_simulation(factory, *, population_id="household-1", policy_id=1):
    simulation = (
        SimulationService(factory)
        .get_or_create_simulation("us", population_id, "household", policy_id)
        .simulation
    )
    return simulation.id


def create_report(factory, simulation_id):
    with factory.begin() as session:
        report = report_service.create_report_output(
            session, "us", simulation_id, year="2025"
        )
        return report.id


def test_create_simulation_existing_row_repairs_dual_write_state(
    orm_session_factory,
):
    with orm_session_factory.begin() as session:
        simulation = Simulation(
            country_id="us",
            api_version="old",
            population_id="household-route-repair",
            population_type="household",
            policy_id=40,
            status="pending",
        )
        session.add(simulation)
        session.flush()
        simulation_id = simulation.id

    response = create_test_client().post(
        "/us/simulation",
        json={
            "population_id": "household-route-repair",
            "population_type": "household",
            "policy_id": 40,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["result"]["id"] == simulation_id
    with orm_session_factory() as session:
        simulation = session.get(Simulation, simulation_id)
        assert simulation.simulation_spec_json is not None
        assert simulation.active_run_id is not None


def test_create_report_existing_row_repairs_dual_write_state(orm_session_factory):
    simulation_id = create_simulation(orm_session_factory, policy_id=41)
    with orm_session_factory.begin() as session:
        report = ReportOutput(
            country_id="us",
            simulation_1_id=simulation_id,
            simulation_2_id=None,
            api_version=get_report_output_cache_version("us"),
            status="pending",
            year="2025",
        )
        session.add(report)
        session.flush()
        report_id = report.id

    response = create_test_client().post(
        "/us/report",
        json={"simulation_1_id": simulation_id, "year": "2025"},
    )

    assert response.status_code == 200
    assert response.get_json()["result"]["id"] == report_id
    with orm_session_factory() as session:
        report = session.get(ReportOutput, report_id)
        assert report.report_spec_json is not None
        assert report.active_run_id is not None


def test_report_post_returns_run_timestamps_for_new_and_existing(
    orm_session_factory,
):
    simulation_id = create_simulation(orm_session_factory, policy_id=42)
    client = create_test_client()

    created = client.post(
        "/us/report", json={"simulation_1_id": simulation_id, "year": "2025"}
    )
    existing = client.post(
        "/us/report", json={"simulation_1_id": simulation_id, "year": "2025"}
    )

    assert created.status_code == 201
    assert existing.status_code == 200
    for response in (created, existing):
        result = response.get_json()["result"]
        assert result["requested_at"] is not None
        assert result["started_at"] is None
        assert result["finished_at"] is None


def test_report_post_rejects_missing_linked_simulations(orm_session_factory):
    simulation_id = create_simulation(orm_session_factory, policy_id=43)
    client = create_test_client()

    missing_primary = client.post(
        "/us/report", json={"simulation_1_id": 999999, "year": "2025"}
    )
    missing_secondary = client.post(
        "/us/report",
        json={
            "simulation_1_id": simulation_id,
            "simulation_2_id": 999999,
            "year": "2025",
        },
    )

    assert missing_primary.status_code == 400
    assert missing_secondary.status_code == 400


def test_simulation_routes_scope_reads_and_writes_to_country(orm_session_factory):
    simulation_id = create_simulation(orm_session_factory, policy_id=44)
    client = create_test_client()

    assert client.get(f"/uk/simulation/{simulation_id}").status_code == 404
    response = client.patch(
        "/uk/simulation",
        json={"id": simulation_id, "status": "complete", "output": {"bad": True}},
    )

    assert response.status_code == 404
    with orm_session_factory() as session:
        assert session.get(Simulation, simulation_id).status == "pending"


def test_report_routes_scope_reads_and_writes_to_country(orm_session_factory):
    simulation_id = create_simulation(orm_session_factory, policy_id=45)
    report_id = create_report(orm_session_factory, simulation_id)
    client = create_test_client()

    assert client.get(f"/uk/report/{report_id}").status_code == 404
    response = client.patch(
        "/uk/report",
        json={"id": report_id, "status": "complete", "output": {"bad": True}},
    )

    assert response.status_code == 404
    with orm_session_factory() as session:
        assert session.get(ReportOutput, report_id).status == "pending"


def test_report_get_serializes_display_run_timestamps(orm_session_factory):
    simulation_id = create_simulation(orm_session_factory, policy_id=46)
    report_id = create_report(orm_session_factory, simulation_id)
    with orm_session_factory.begin() as session:
        report_service.update_report_output(
            session, "us", report_id, status="complete", output={"ok": True}
        )
        report = session.get(ReportOutput, report_id)
        run = session.get(ReportOutputRun, report.latest_successful_run_id)
        run.requested_at = datetime(2026, 5, 4, 12, 0)
        run.started_at = datetime(2026, 5, 4, 12, 1)
        run.finished_at = datetime(2026, 5, 4, 12, 2)

    result = create_test_client().get(f"/us/report/{report_id}").get_json()["result"]

    assert result["requested_at"] == "2026-05-04T12:00:00Z"
    assert result["started_at"] == "2026-05-04T12:01:00Z"
    assert result["finished_at"] == "2026-05-04T12:02:00Z"


def test_report_patch_updates_active_rerun_and_preserves_success(
    orm_session_factory,
):
    simulation_id = create_simulation(orm_session_factory, policy_id=47)
    report_id = create_report(orm_session_factory, simulation_id)
    with orm_session_factory.begin() as session:
        report_service.update_report_output(
            session, "us", report_id, status="complete", output={"old": True}
        )
        report = session.get(ReportOutput, report_id)
        successful_id = report.latest_successful_run_id
        rerun = run_service.create_report_output_run(
            session, report_id, trigger_type="rerun"
        )
        report.active_run_id = rerun.id
        rerun_id = rerun.id

    running = create_test_client().patch(
        "/us/report", json={"id": report_id, "status": "running"}
    )
    failed = create_test_client().patch(
        "/us/report",
        json={"id": report_id, "status": "error", "error_message": "failed"},
    )

    assert running.status_code == 200
    assert running.get_json()["result"]["started_at"] is not None
    assert failed.status_code == 200
    assert failed.get_json()["result"]["finished_at"] is not None
    with orm_session_factory() as session:
        report = session.get(ReportOutput, report_id)
        rerun = session.get(ReportOutputRun, rerun_id)
        assert report.latest_successful_run_id == successful_id
        assert rerun.status == "error"


def test_report_patch_complete_promotes_active_rerun(orm_session_factory):
    simulation_id = create_simulation(orm_session_factory, policy_id=48)
    report_id = create_report(orm_session_factory, simulation_id)
    with orm_session_factory.begin() as session:
        report_service.update_report_output(
            session, "us", report_id, status="complete", output={"old": True}
        )
        report = session.get(ReportOutput, report_id)
        rerun = run_service.create_report_output_run(
            session, report_id, trigger_type="rerun"
        )
        report.active_run_id = rerun.id
        rerun_id = rerun.id

    response = create_test_client().patch(
        "/us/report",
        json={"id": report_id, "status": "complete", "output": {"new": True}},
    )

    assert response.status_code == 200
    with orm_session_factory() as session:
        report = session.get(ReportOutput, report_id)
        assert report.active_run_id is None
        assert report.latest_successful_run_id == rerun_id


def test_simulation_v1_routes_keep_json_fields_as_strings(orm_session_factory):
    simulation_id = create_simulation(orm_session_factory, policy_id=49)
    output = {"result": "ok", "values": [1, 2, 3]}

    patched = create_test_client().patch(
        "/us/simulation",
        json={"id": simulation_id, "status": "complete", "output": output},
    )
    fetched = create_test_client().get(f"/us/simulation/{simulation_id}")

    for response in (patched, fetched):
        result = response.get_json()["result"]
        assert isinstance(result["output"], str)
        assert json.loads(result["output"]) == output
        assert isinstance(result["simulation_spec_json"], str)
    with orm_session_factory() as session:
        simulation = session.get(Simulation, simulation_id)
        assert simulation.output == output
        assert isinstance(simulation.simulation_spec_json, dict)
