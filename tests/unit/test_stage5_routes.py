import json

from flask import Flask

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.routes.report_output_routes import report_output_bp
from policyengine_api.routes.simulation_routes import simulation_bp
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.simulation_service import SimulationService


simulation_service = SimulationService()
report_output_service = ReportOutputService()


def create_test_client() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(simulation_bp)
    app.register_blueprint(report_output_bp)
    return app.test_client()


def test_create_simulation_existing_row_repairs_dual_write_state(test_db):
    test_db.query(
        """INSERT INTO simulations
        (country_id, api_version, population_id, population_type, policy_id, status)
        VALUES (?, ?, ?, ?, ?, ?)""",
        ("us", "us-system-1.0.0", "household_route_repair", "household", 40, "pending"),
    )
    simulation = test_db.query(
        "SELECT * FROM simulations ORDER BY id DESC LIMIT 1"
    ).fetchone()

    client = create_test_client()
    response = client.post(
        "/us/simulation",
        json={
            "population_id": "household_route_repair",
            "population_type": "household",
            "policy_id": 40,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["message"] == "Simulation already exists"
    assert payload["result"]["id"] == simulation["id"]

    stored_simulation = test_db.query(
        "SELECT * FROM simulations WHERE id = ?",
        (simulation["id"],),
    ).fetchone()
    assert stored_simulation["simulation_spec_json"] is not None
    assert stored_simulation["active_run_id"] is not None

    run = test_db.query(
        "SELECT * FROM simulation_runs WHERE simulation_id = ?",
        (simulation["id"],),
    ).fetchone()
    assert run is not None


def test_create_report_output_existing_row_repairs_dual_write_state(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_report",
        population_type="household",
        policy_id=41,
    )
    test_db.query(
        """
        INSERT INTO report_outputs (
            country_id, simulation_1_id, simulation_2_id, api_version, status, year
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "us",
            simulation["id"],
            None,
            get_report_output_cache_version("us"),
            "pending",
            "2025",
        ),
    )
    report_output = test_db.query(
        "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    client = create_test_client()
    response = client.post(
        "/us/report",
        json={
            "simulation_1_id": simulation["id"],
            "simulation_2_id": None,
            "year": "2025",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["message"] == "Report output already exists"
    assert payload["result"]["id"] == report_output["id"]

    stored_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report_output["id"],),
    ).fetchone()
    assert stored_report["report_spec_json"] is not None
    assert stored_report["active_run_id"] is not None

    run = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report_output["id"],),
    ).fetchone()
    assert run is not None
    snapshot = run["report_spec_snapshot_json"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    assert snapshot["report_kind"] == "household_single"


def test_get_report_output_wrong_country_returns_not_found(test_db):
    test_db.query(
        """
        INSERT INTO report_outputs (
            country_id, simulation_1_id, simulation_2_id, api_version, status, year
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("us", 999, None, get_report_output_cache_version("us"), "pending", "2025"),
    )
    report_output = test_db.query(
        "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    client = create_test_client()
    response = client.get(f"/uk/report/{report_output['id']}")

    assert response.status_code == 404


def test_patch_report_output_wrong_country_returns_not_found_and_does_not_mutate(
    test_db,
):
    test_db.query(
        """
        INSERT INTO report_outputs (
            country_id, simulation_1_id, simulation_2_id, api_version, status, year
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("us", 1000, None, get_report_output_cache_version("us"), "pending", "2025"),
    )
    report_output = test_db.query(
        "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    client = create_test_client()
    response = client.patch(
        "/uk/report",
        json={
            "id": report_output["id"],
            "status": "complete",
            "output": json.dumps({"should_not": "persist"}),
        },
    )

    assert response.status_code == 404

    stored_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report_output["id"],),
    ).fetchone()
    assert stored_report["country_id"] == "us"
    assert stored_report["status"] == "pending"
    assert stored_report["output"] is None
