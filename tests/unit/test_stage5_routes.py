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


def test_create_report_output_with_explicit_spec_persists_it(test_db):
    baseline_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/ny",
        population_type="geography",
        policy_id=45,
    )
    reform_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/ny",
        population_type="geography",
        policy_id=46,
    )

    client = create_test_client()
    response = client.post(
        "/us/report",
        json={
            "simulation_1_id": baseline_simulation["id"],
            "simulation_2_id": reform_simulation["id"],
            "year": "2026",
            "report_spec_schema_version": 1,
            "report_spec": {
                "country_id": "us",
                "report_kind": "economy_comparison",
                "time_period": "2026",
                "region": "state/ny",
                "baseline_policy_id": 45,
                "reform_policy_id": 46,
                "dataset": "enhanced_us_household",
                "target": "cliff",
                "options": {"view": "tax"},
            },
        },
    )

    assert response.status_code == 201
    report_id = response.get_json()["result"]["id"]

    stored_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report_id,),
    ).fetchone()
    assert stored_report["report_kind"] == "economy_comparison"
    assert stored_report["report_spec_schema_version"] == 1
    assert stored_report["report_spec_status"] == "explicit"

    report_spec = stored_report["report_spec_json"]
    if isinstance(report_spec, str):
        report_spec = json.loads(report_spec)
    assert report_spec["dataset"] == "enhanced_us_household"
    assert report_spec["target"] == "cliff"
    assert report_spec["options"] == {"view": "tax"}

    run = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report_id,),
    ).fetchone()
    assert run is not None
    snapshot = run["report_spec_snapshot_json"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    assert snapshot["dataset"] == "enhanced_us_household"
    assert snapshot["target"] == "cliff"
    assert snapshot["options"] == {"view": "tax"}


def test_create_report_output_missing_primary_simulation_returns_bad_request(test_db):
    client = create_test_client()
    response = client.post(
        "/us/report",
        json={
            "simulation_1_id": 999999,
            "simulation_2_id": None,
            "year": "2025",
        },
    )

    assert response.status_code == 400

    report_rows = test_db.query("SELECT * FROM report_outputs").fetchall()
    report_run_rows = test_db.query("SELECT * FROM report_output_runs").fetchall()
    assert report_rows == []
    assert report_run_rows == []


def test_create_report_output_missing_secondary_simulation_returns_bad_request(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_missing_secondary",
        population_type="household",
        policy_id=42,
    )

    client = create_test_client()
    response = client.post(
        "/us/report",
        json={
            "simulation_1_id": simulation["id"],
            "simulation_2_id": simulation["id"] + 999999,
            "year": "2025",
        },
    )

    assert response.status_code == 400

    report_rows = test_db.query(
        "SELECT * FROM report_outputs WHERE simulation_1_id = ?",
        (simulation["id"],),
    ).fetchall()
    report_run_rows = test_db.query("SELECT * FROM report_output_runs").fetchall()
    assert report_rows == []
    assert report_run_rows == []


def test_get_simulation_wrong_country_returns_not_found(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_wrong_country_get",
        population_type="household",
        policy_id=43,
    )

    client = create_test_client()
    response = client.get(f"/uk/simulation/{simulation['id']}")

    assert response.status_code == 404


def test_patch_simulation_wrong_country_returns_not_found_and_does_not_mutate(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_wrong_country_patch",
        population_type="household",
        policy_id=44,
    )

    client = create_test_client()
    response = client.patch(
        "/uk/simulation",
        json={
            "id": simulation["id"],
            "status": "complete",
            "output": json.dumps({"should_not": "persist"}),
        },
    )

    assert response.status_code == 404

    stored_simulation = test_db.query(
        "SELECT * FROM simulations WHERE id = ?",
        (simulation["id"],),
    ).fetchone()
    assert stored_simulation["country_id"] == "us"
    assert stored_simulation["status"] == "pending"
    assert stored_simulation["output"] is None


def test_patch_simulation_persists_run_metadata_fields(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_metadata",
        population_type="household",
        policy_id=47,
    )

    client = create_test_client()
    response = client.patch(
        "/us/simulation",
        json={
            "id": simulation["id"],
            "status": "complete",
            "output": json.dumps({"ok": True}),
            "country_package_version": "1.620.0",
            "policyengine_version": "0.94.2",
            "data_version": "2026.04.16",
            "runtime_app_name": "policyengine-app-v2",
        },
    )

    assert response.status_code == 200
    run = test_db.query(
        "SELECT * FROM simulation_runs WHERE simulation_id = ?",
        (simulation["id"],),
    ).fetchone()
    assert run["country_package_version"] == "1.620.0"
    assert run["policyengine_version"] == "0.94.2"
    assert run["data_version"] == "2026.04.16"
    assert run["runtime_app_name"] == "policyengine-app-v2"


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


def test_patch_report_output_persists_run_metadata_fields(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/wa",
        population_type="geography",
        policy_id=48,
    )
    report_output = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2026",
    )

    client = create_test_client()
    response = client.patch(
        "/us/report",
        json={
            "id": report_output["id"],
            "status": "complete",
            "output": json.dumps({"result": "ok"}),
            "country_package_version": "1.621.0",
            "policyengine_version": "0.95.0",
            "data_version": "2026.04.17",
            "runtime_app_name": "policyengine-app-v2",
            "resolved_dataset": "enhanced_us_household",
        },
    )

    assert response.status_code == 200
    run = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report_output["id"],),
    ).fetchone()
    assert run["country_package_version"] == "1.621.0"
    assert run["policyengine_version"] == "0.95.0"
    assert run["data_version"] == "2026.04.17"
    assert run["runtime_app_name"] == "policyengine-app-v2"
    assert run["resolved_dataset"] == "enhanced_us_household"


def test_patch_report_output_preserves_stored_explicit_report_spec(test_db):
    baseline_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/or",
        population_type="geography",
        policy_id=49,
    )
    reform_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/or",
        population_type="geography",
        policy_id=50,
    )

    client = create_test_client()
    create_response = client.post(
        "/us/report",
        json={
            "simulation_1_id": baseline_simulation["id"],
            "simulation_2_id": reform_simulation["id"],
            "year": "2026",
            "report_spec_schema_version": 1,
            "report_spec": {
                "country_id": "us",
                "report_kind": "economy_comparison",
                "time_period": "2026",
                "region": "state/or",
                "baseline_policy_id": 49,
                "reform_policy_id": 50,
                "dataset": "enhanced_us_household",
                "target": "cliff",
                "options": {"view": "tax"},
            },
        },
    )
    report_id = create_response.get_json()["result"]["id"]

    patch_response = client.patch(
        "/us/report",
        json={
            "id": report_id,
            "status": "complete",
            "output": json.dumps({"result": "ok"}),
        },
    )

    assert patch_response.status_code == 200
    stored_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report_id,),
    ).fetchone()
    assert stored_report["report_spec_status"] == "explicit"
    report_spec = stored_report["report_spec_json"]
    if isinstance(report_spec, str):
        report_spec = json.loads(report_spec)
    assert report_spec["dataset"] == "enhanced_us_household"
    assert report_spec["target"] == "cliff"
    assert report_spec["options"] == {"view": "tax"}

    run = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report_id,),
    ).fetchone()
    assert run is not None
    snapshot = run["report_spec_snapshot_json"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    assert snapshot["dataset"] == "enhanced_us_household"
    assert snapshot["target"] == "cliff"
    assert snapshot["options"] == {"view": "tax"}


def test_patch_report_output_metadata_only_preserves_stored_explicit_report_spec(test_db):
    baseline_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/nj",
        population_type="geography",
        policy_id=51,
    )
    reform_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/nj",
        population_type="geography",
        policy_id=52,
    )

    client = create_test_client()
    create_response = client.post(
        "/us/report",
        json={
            "simulation_1_id": baseline_simulation["id"],
            "simulation_2_id": reform_simulation["id"],
            "year": "2026",
            "report_spec_schema_version": 1,
            "report_spec": {
                "country_id": "us",
                "report_kind": "economy_comparison",
                "time_period": "2026",
                "region": "state/nj",
                "baseline_policy_id": 51,
                "reform_policy_id": 52,
                "dataset": "enhanced_us_household",
                "target": "cliff",
                "options": {"view": "tax"},
            },
        },
    )
    report_id = create_response.get_json()["result"]["id"]

    patch_response = client.patch(
        "/us/report",
        json={
            "id": report_id,
            "policyengine_version": "0.95.1",
            "runtime_app_name": "policyengine-app-v2",
        },
    )

    assert patch_response.status_code == 200
    stored_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report_id,),
    ).fetchone()
    assert stored_report["report_spec_status"] == "explicit"
    report_spec = stored_report["report_spec_json"]
    if isinstance(report_spec, str):
        report_spec = json.loads(report_spec)
    assert report_spec["dataset"] == "enhanced_us_household"
    assert report_spec["target"] == "cliff"
    assert report_spec["options"] == {"view": "tax"}

    run = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report_id,),
    ).fetchone()
    assert run is not None
    assert run["policyengine_version"] == "0.95.1"
    assert run["runtime_app_name"] == "policyengine-app-v2"
    snapshot = run["report_spec_snapshot_json"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    assert snapshot["dataset"] == "enhanced_us_household"
    assert snapshot["target"] == "cliff"
    assert snapshot["options"] == {"view": "tax"}
