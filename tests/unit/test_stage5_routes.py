import json

from flask import Flask

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.routes.report_output_routes import report_output_bp
from policyengine_api.routes.simulation_routes import simulation_bp
from policyengine_api.services.report_output_id_map_service import (
    ReportOutputIdMapService,
)
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.report_run_service import ReportRunService
from policyengine_api.services.simulation_run_service import SimulationRunService
from policyengine_api.services.simulation_service import SimulationService


simulation_service = SimulationService()
report_output_service = ReportOutputService()
report_run_service = ReportRunService()
report_output_id_map_service = ReportOutputIdMapService()
simulation_run_service = SimulationRunService()


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


def test_create_report_output_existing_stale_row_adds_current_run(test_db):
    stale_version = "r0stale1"
    current_version = get_report_output_cache_version("us")
    assert stale_version != current_version
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_stale_report_create",
        population_type="household",
        policy_id=42,
    )
    test_db.query(
        """
        INSERT INTO report_outputs (
            country_id, simulation_1_id, simulation_2_id, api_version, status, output, year
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "us",
            simulation["id"],
            None,
            stale_version,
            "complete",
            json.dumps({"result": "stale"}),
            "2026",
        ),
    )
    stale_report = test_db.query(
        "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    client = create_test_client()
    response = client.post(
        "/us/report",
        json={
            "simulation_1_id": simulation["id"],
            "year": "2026",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["id"] == stale_report["id"]
    assert payload["result"]["status"] == "pending"
    assert payload["result"]["output"] is None
    assert payload["result"]["api_version"] == current_version

    report_rows = test_db.query(
        """
        SELECT * FROM report_outputs
        WHERE country_id = ? AND simulation_1_id = ? AND year = ?
        """,
        ("us", simulation["id"], "2026"),
    ).fetchall()
    assert len(report_rows) == 1

    runs = test_db.query(
        """
        SELECT * FROM report_output_runs
        WHERE report_output_id = ?
        ORDER BY run_sequence ASC
        """,
        (stale_report["id"],),
    ).fetchall()
    assert len(runs) == 2
    assert runs[0]["report_cache_version"] == stale_version
    assert runs[0]["output"] == json.dumps({"result": "stale"})
    assert runs[1]["report_cache_version"] == current_version
    assert runs[1]["status"] == "pending"


def test_post_report_output_returns_timestamp_fields_for_new_and_existing_report(
    test_db,
):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_report_timestamps",
        population_type="household",
        policy_id=46,
    )

    client = create_test_client()
    response = client.post(
        "/us/report",
        json={
            "simulation_1_id": simulation["id"],
            "simulation_2_id": None,
            "year": "2025",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    created_report = payload["result"]
    assert created_report["requested_at"] is not None
    assert created_report["started_at"] is None
    assert created_report["finished_at"] is None

    existing_response = client.post(
        "/us/report",
        json={
            "simulation_1_id": simulation["id"],
            "simulation_2_id": None,
            "year": "2025",
        },
    )

    assert existing_response.status_code == 200
    existing_payload = existing_response.get_json()
    existing_report = existing_payload["result"]
    assert existing_report["id"] == created_report["id"]
    assert existing_report["requested_at"] is not None
    assert existing_report["started_at"] is None
    assert existing_report["finished_at"] is None


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
    assert stored_report["report_identity_hash"] is not None
    assert stored_report["report_identity_schema_version"] == 1

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


def test_create_report_output_same_explicit_spec_returns_existing_row(test_db):
    baseline_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/va",
        population_type="geography",
        policy_id=53,
    )
    reform_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/va",
        population_type="geography",
        policy_id=54,
    )
    payload = {
        "simulation_1_id": baseline_simulation["id"],
        "simulation_2_id": reform_simulation["id"],
        "year": "2026",
        "report_spec_schema_version": 1,
        "report_spec": {
            "country_id": "us",
            "report_kind": "economy_comparison",
            "time_period": "2026",
            "region": "state/va",
            "baseline_policy_id": 53,
            "reform_policy_id": 54,
            "dataset": "enhanced_us_household",
            "target": "cliff",
            "options": {"view": "tax"},
        },
    }

    client = create_test_client()
    first_response = client.post("/us/report", json=payload)
    second_response = client.post("/us/report", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert (
        first_response.get_json()["result"]["id"]
        == second_response.get_json()["result"]["id"]
    )


def test_create_report_output_same_identity_after_cache_version_change_reuses_row(
    test_db, monkeypatch
):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_cache_version_reuse",
        population_type="household",
        policy_id=75,
    )
    client = create_test_client()
    payload = {
        "simulation_1_id": simulation["id"],
        "simulation_2_id": None,
        "year": "2026",
    }

    first_response = client.post("/us/report", json=payload)
    monkeypatch.setattr(
        "policyengine_api.services.report_output_service.get_report_output_cache_version",
        lambda country_id: f"{country_id}-new-report-cache-version",
    )
    second_response = client.post("/us/report", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert (
        first_response.get_json()["result"]["id"]
        == second_response.get_json()["result"]["id"]
    )

    rows = test_db.query("SELECT * FROM report_outputs").fetchall()
    assert len(rows) == 1


def test_create_report_output_distinct_explicit_specs_create_distinct_rows(test_db):
    baseline_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/md",
        population_type="geography",
        policy_id=55,
    )
    reform_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/md",
        population_type="geography",
        policy_id=56,
    )

    client = create_test_client()
    default_response = client.post(
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
                "region": "state/md",
                "baseline_policy_id": 55,
                "reform_policy_id": 56,
                "dataset": "default",
                "target": "general",
                "options": {},
            },
        },
    )
    cliff_response = client.post(
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
                "region": "state/md",
                "baseline_policy_id": 55,
                "reform_policy_id": 56,
                "dataset": "enhanced_us_household",
                "target": "cliff",
                "options": {"view": "tax"},
            },
        },
    )

    assert default_response.status_code == 201
    assert cliff_response.status_code == 201
    assert (
        default_response.get_json()["result"]["id"]
        != cliff_response.get_json()["result"]["id"]
    )


def test_create_report_output_explicit_spec_validates_requested_simulations_before_reuse(
    test_db,
):
    baseline_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/ma",
        population_type="geography",
        policy_id=70,
    )
    reform_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/ma",
        population_type="geography",
        policy_id=71,
    )
    mismatched_baseline_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/ma",
        population_type="geography",
        policy_id=72,
    )
    payload = {
        "simulation_1_id": baseline_simulation["id"],
        "simulation_2_id": reform_simulation["id"],
        "year": "2026",
        "report_spec_schema_version": 1,
        "report_spec": {
            "country_id": "us",
            "report_kind": "economy_comparison",
            "time_period": "2026",
            "region": "state/ma",
            "baseline_policy_id": 70,
            "reform_policy_id": 71,
            "dataset": "enhanced_us_household",
            "target": "cliff",
            "options": {"view": "tax"},
        },
    }

    client = create_test_client()
    create_response = client.post("/us/report", json=payload)
    missing_response = client.post(
        "/us/report",
        json={
            **payload,
            "simulation_1_id": 999999,
        },
    )
    mismatched_response = client.post(
        "/us/report",
        json={
            **payload,
            "simulation_1_id": mismatched_baseline_simulation["id"],
        },
    )

    assert create_response.status_code == 201
    assert missing_response.status_code == 400
    assert mismatched_response.status_code == 400

    report_rows = test_db.query("SELECT * FROM report_outputs").fetchall()
    assert len(report_rows) == 1


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


def test_patch_simulation_explicit_run_id_updates_only_that_run(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_explicit_simulation_run",
        population_type="household",
        policy_id=78,
    )
    simulation_service.update_simulation(
        country_id="us",
        simulation_id=simulation["id"],
        status="complete",
        output=json.dumps({"result": "initial"}),
    )
    initial_run = test_db.query(
        "SELECT * FROM simulation_runs WHERE simulation_id = ?",
        (simulation["id"],),
    ).fetchone()
    rerun = simulation_run_service.create_simulation_run(
        simulation["id"],
        trigger_type="rerun",
    )

    client = create_test_client()
    response = client.patch(
        "/us/simulation",
        json={
            "id": simulation["id"],
            "simulation_run_id": rerun["id"],
            "status": "complete",
            "output": json.dumps({"result": "explicit rerun"}),
        },
    )

    assert response.status_code == 200
    initial_run_after = test_db.query(
        "SELECT * FROM simulation_runs WHERE id = ?",
        (initial_run["id"],),
    ).fetchone()
    rerun_after = test_db.query(
        "SELECT * FROM simulation_runs WHERE id = ?",
        (rerun["id"],),
    ).fetchone()
    assert initial_run_after["output"] == json.dumps({"result": "initial"})
    assert rerun_after["output"] == json.dumps({"result": "explicit rerun"})


def test_patch_simulation_explicit_run_id_response_uses_that_run(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_explicit_simulation_run_response",
        population_type="household",
        policy_id=79,
    )
    simulation_service.update_simulation(
        country_id="us",
        simulation_id=simulation["id"],
        status="complete",
        output=json.dumps({"result": "initial"}),
    )
    older_run = simulation_run_service.create_simulation_run(
        simulation["id"],
        status="complete",
        trigger_type="rerun",
        output=json.dumps({"result": "older before patch"}),
    )
    newer_run = simulation_run_service.create_simulation_run(
        simulation["id"],
        status="complete",
        trigger_type="rerun",
        output=json.dumps({"result": "newer display"}),
    )
    test_db.query(
        """
        UPDATE simulations
        SET latest_successful_run_id = ?
        WHERE id = ?
        """,
        (newer_run["id"], simulation["id"]),
    )

    client = create_test_client()
    response = client.patch(
        "/us/simulation",
        json={
            "id": simulation["id"],
            "simulation_run_id": older_run["id"],
            "status": "complete",
            "output": json.dumps({"result": "older patched"}),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["output"] == json.dumps({"result": "older patched"})

    get_response = client.get(f"/us/simulation/{simulation['id']}")
    assert get_response.status_code == 200
    get_payload = get_response.get_json()
    assert get_payload["result"]["output"] == json.dumps({"result": "newer display"})


def test_patch_simulation_rejects_non_string_run_metadata(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_invalid_metadata",
        population_type="household",
        policy_id=73,
    )

    client = create_test_client()
    response = client.patch(
        "/us/simulation",
        json={
            "id": simulation["id"],
            "country_package_version": 123,
        },
    )

    assert response.status_code == 400


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


def test_get_report_output_legacy_id_wrong_country_returns_not_found(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_alias_wrong_country",
        population_type="household",
        policy_id=56,
    )
    canonical_report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2025",
    )
    report_output_id_map_service.set_mapping(
        legacy_report_output_id=2000,
        canonical_report_output_id=canonical_report["id"],
    )

    client = create_test_client()
    response = client.get("/uk/report/2000")

    assert response.status_code == 404


def test_get_report_output_legacy_id_resolves_to_canonical_display_run(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_alias",
        population_type="household",
        policy_id=57,
    )
    canonical_report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2025",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=canonical_report["id"],
        status="complete",
        output=json.dumps({"result": "canonical"}),
    )
    test_db.query(
        """
        INSERT INTO report_outputs (
            id, country_id, simulation_1_id, simulation_2_id, api_version, status, output, year
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            2001,
            "us",
            simulation["id"],
            None,
            "r0legacy1",
            "error",
            json.dumps({"result": "legacy"}),
            "2025",
        ),
    )
    test_db.query(
        """
        INSERT INTO legacy_report_output_id_map (
            legacy_report_output_id, canonical_report_output_id
        ) VALUES (?, ?)
        """,
        (2001, canonical_report["id"]),
    )

    client = create_test_client()
    response = client.get("/us/report/2001")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["id"] == 2001
    assert payload["result"]["status"] == "complete"
    assert payload["result"]["output"] == json.dumps({"result": "canonical"})
    assert payload["result"]["api_version"] == get_report_output_cache_version("us")


def test_get_report_output_reads_malformed_legacy_row_without_runs_or_identity(
    test_db,
):
    household_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_legacy_malformed",
        population_type="household",
        policy_id=58,
    )
    geography_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/co",
        population_type="geography",
        policy_id=59,
    )
    test_db.query(
        """
        INSERT INTO report_outputs (
            country_id, simulation_1_id, simulation_2_id, api_version, status, output, year
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "us",
            household_simulation["id"],
            geography_simulation["id"],
            "r0legacy-malformed",
            "error",
            json.dumps({"result": "legacy-malformed"}),
            "2025",
        ),
    )
    malformed_report = test_db.query(
        "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    client = create_test_client()
    response = client.get(f"/us/report/{malformed_report['id']}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["id"] == malformed_report["id"]
    assert payload["result"]["status"] == "error"
    assert payload["result"]["output"] == json.dumps({"result": "legacy-malformed"})
    assert payload["result"]["api_version"] == "r0legacy-malformed"


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


def test_patch_report_output_accepts_running_status(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_running_report",
        population_type="household",
        policy_id=45,
    )
    report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2025",
    )

    client = create_test_client()
    response = client.patch(
        "/us/report",
        json={
            "id": report["id"],
            "status": "running",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["status"] == "running"
    assert payload["result"]["requested_at"] is not None
    assert payload["result"]["started_at"] is not None
    assert payload["result"]["finished_at"] is None


def test_get_report_output_serializes_display_run_timestamps(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_get_timestamp",
        population_type="household",
        policy_id=47,
    )
    report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2025",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=report["id"],
        status="complete",
        output=json.dumps({"ok": True}),
    )
    run = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report["id"],),
    ).fetchone()
    test_db.query(
        """
        UPDATE report_output_runs
        SET requested_at = ?, started_at = ?, finished_at = ?
        WHERE id = ?
        """,
        (
            "2026-05-04 12:00:00",
            "2026-05-04 12:01:00",
            "2026-05-04 12:02:00",
            run["id"],
        ),
    )

    client = create_test_client()
    response = client.get(f"/us/report/{report['id']}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["requested_at"] == "2026-05-04T12:00:00Z"
    assert payload["result"]["started_at"] == "2026-05-04T12:01:00Z"
    assert payload["result"]["finished_at"] == "2026-05-04T12:02:00Z"


def test_patch_report_output_running_uses_active_rerun_route_path(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_active_running_rerun",
        population_type="household",
        policy_id=48,
    )
    report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2025",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=report["id"],
        status="complete",
        output=json.dumps({"ok": True}),
    )
    completed_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report["id"],),
    ).fetchone()
    successful_run_id = completed_report["latest_successful_run_id"]
    rerun = report_run_service.create_report_output_run(
        report["id"], trigger_type="rerun"
    )
    test_db.query(
        """
        UPDATE report_outputs
        SET active_run_id = ?, latest_successful_run_id = ?
        WHERE id = ?
        """,
        (rerun["id"], successful_run_id, report["id"]),
    )

    client = create_test_client()
    response = client.patch(
        "/us/report",
        json={
            "id": report["id"],
            "status": "running",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["status"] == "running"
    assert payload["result"]["started_at"] is not None
    assert payload["result"]["finished_at"] is None

    successful_run = test_db.query(
        "SELECT * FROM report_output_runs WHERE id = ?",
        (successful_run_id,),
    ).fetchone()
    active_run = test_db.query(
        "SELECT * FROM report_output_runs WHERE id = ?",
        (rerun["id"],),
    ).fetchone()
    assert successful_run["status"] == "complete"
    assert successful_run["finished_at"] is not None
    assert active_run["status"] == "running"
    assert active_run["started_at"] is not None
    assert active_run["finished_at"] is None


def test_patch_report_output_error_uses_active_rerun_timestamp_route_path(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_active_error_rerun",
        population_type="household",
        policy_id=49,
    )
    report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2025",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=report["id"],
        status="complete",
        output=json.dumps({"ok": True}),
    )
    completed_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report["id"],),
    ).fetchone()
    successful_run_id = completed_report["latest_successful_run_id"]
    test_db.query(
        """
        UPDATE report_output_runs
        SET requested_at = ?, started_at = ?, finished_at = ?
        WHERE id = ?
        """,
        (
            "2026-05-04 10:00:00",
            "2026-05-04 10:01:00",
            "2026-05-04 10:02:00",
            successful_run_id,
        ),
    )
    rerun = report_run_service.create_report_output_run(
        report["id"], trigger_type="rerun"
    )
    test_db.query(
        """
        UPDATE report_outputs
        SET active_run_id = ?, latest_successful_run_id = ?
        WHERE id = ?
        """,
        (rerun["id"], successful_run_id, report["id"]),
    )

    client = create_test_client()
    response = client.patch(
        "/us/report",
        json={
            "id": report["id"],
            "status": "error",
            "error_message": "rerun failed",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["status"] == "error"
    assert payload["result"]["finished_at"] is not None
    assert payload["result"]["finished_at"] != "2026-05-04T10:02:00Z"


def test_patch_report_output_complete_promotes_active_rerun_route_path(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_active_complete_rerun",
        population_type="household",
        policy_id=50,
    )
    report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2025",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=report["id"],
        status="complete",
        output=json.dumps({"ok": True}),
    )
    completed_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report["id"],),
    ).fetchone()
    successful_run_id = completed_report["latest_successful_run_id"]
    rerun = report_run_service.create_report_output_run(
        report["id"], trigger_type="rerun"
    )
    test_db.query(
        """
        UPDATE report_outputs
        SET active_run_id = ?, latest_successful_run_id = ?
        WHERE id = ?
        """,
        (rerun["id"], successful_run_id, report["id"]),
    )

    client = create_test_client()
    response = client.patch(
        "/us/report",
        json={
            "id": report["id"],
            "status": "complete",
            "output": json.dumps({"ok": "rerun"}),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["status"] == "complete"
    assert payload["result"]["finished_at"] is not None

    stored_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?",
        (report["id"],),
    ).fetchone()
    assert stored_report["active_run_id"] is None
    assert stored_report["latest_successful_run_id"] == rerun["id"]


def test_patch_report_output_explicit_run_id_updates_only_that_run(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_explicit_report_run",
        population_type="household",
        policy_id=76,
    )
    report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2026",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=report["id"],
        status="complete",
        output=json.dumps({"result": "initial"}),
    )
    initial_run = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report["id"],),
    ).fetchone()
    rerun = report_run_service.create_report_output_run(
        report["id"], trigger_type="rerun"
    )

    client = create_test_client()
    response = client.patch(
        "/us/report",
        json={
            "id": report["id"],
            "report_output_run_id": rerun["id"],
            "status": "complete",
            "output": json.dumps({"result": "explicit rerun"}),
        },
    )

    assert response.status_code == 200
    initial_run_after = test_db.query(
        "SELECT * FROM report_output_runs WHERE id = ?",
        (initial_run["id"],),
    ).fetchone()
    rerun_after = test_db.query(
        "SELECT * FROM report_output_runs WHERE id = ?",
        (rerun["id"],),
    ).fetchone()
    assert initial_run_after["output"] == json.dumps({"result": "initial"})
    assert rerun_after["output"] == json.dumps({"result": "explicit rerun"})


def test_patch_report_output_explicit_run_id_response_uses_that_run(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_explicit_report_run_response",
        population_type="household",
        policy_id=78,
    )
    report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2026",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=report["id"],
        status="complete",
        output=json.dumps({"result": "initial"}),
    )
    older_run = report_run_service.create_report_output_run(
        report["id"],
        status="complete",
        trigger_type="rerun",
        output=json.dumps({"result": "older before patch"}),
    )
    newer_run = report_run_service.create_report_output_run(
        report["id"],
        status="complete",
        trigger_type="rerun",
        output=json.dumps({"result": "newer display"}),
    )

    client = create_test_client()
    response = client.patch(
        "/us/report",
        json={
            "id": report["id"],
            "report_output_run_id": older_run["id"],
            "status": "complete",
            "output": json.dumps({"result": "older patched"}),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["output"] == json.dumps({"result": "older patched"})
    assert payload["result"]["finished_at"] is not None

    get_response = client.get(f"/us/report/{report['id']}")
    assert get_response.status_code == 200
    get_payload = get_response.get_json()
    assert get_payload["result"]["output"] == json.dumps({"result": "newer display"})

    stored_report = test_db.query(
        "SELECT latest_successful_run_id FROM report_outputs WHERE id = ?",
        (report["id"],),
    ).fetchone()
    assert stored_report["latest_successful_run_id"] == newer_run["id"]


def test_patch_report_output_explicit_run_id_through_legacy_id_updates_canonical_run(
    test_db,
):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_legacy_explicit_report_run",
        population_type="household",
        policy_id=79,
    )
    canonical_report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2026",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=canonical_report["id"],
        status="complete",
        output=json.dumps({"result": "initial"}),
    )
    initial_run = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (canonical_report["id"],),
    ).fetchone()
    rerun = report_run_service.create_report_output_run(
        canonical_report["id"], trigger_type="rerun"
    )
    report_output_id_map_service.set_mapping(
        legacy_report_output_id=3002,
        canonical_report_output_id=canonical_report["id"],
    )

    client = create_test_client()
    response = client.patch(
        "/us/report",
        json={
            "id": 3002,
            "report_output_run_id": rerun["id"],
            "status": "complete",
            "output": json.dumps({"result": "legacy explicit rerun"}),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["id"] == 3002

    initial_run_after = test_db.query(
        "SELECT * FROM report_output_runs WHERE id = ?",
        (initial_run["id"],),
    ).fetchone()
    rerun_after = test_db.query(
        "SELECT * FROM report_output_runs WHERE id = ?",
        (rerun["id"],),
    ).fetchone()
    assert initial_run_after["output"] == json.dumps({"result": "initial"})
    assert rerun_after["report_output_id"] == canonical_report["id"]
    assert rerun_after["output"] == json.dumps({"result": "legacy explicit rerun"})


def test_create_report_rerun_via_canonical_id_creates_canonical_linked_runs(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_canonical_rerun",
        population_type="household",
        policy_id=80,
    )
    canonical_report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2026",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=canonical_report["id"],
        status="complete",
        output=json.dumps({"result": "canonical"}),
    )

    client = create_test_client()
    response = client.post(f"/us/report/{canonical_report['id']}/rerun", json={})

    assert response.status_code == 201
    result = response.get_json()["result"]
    assert result["requested_report_output_id"] == canonical_report["id"]
    assert result["report_output_id"] == canonical_report["id"]
    assert len(result["simulation_run_ids"]) == 1

    report_runs = test_db.query(
        """
        SELECT * FROM report_output_runs
        WHERE report_output_id = ?
        ORDER BY run_sequence
        """,
        (canonical_report["id"],),
    ).fetchall()
    assert len(report_runs) == 2
    assert report_runs[0]["trigger_type"] == "initial"
    assert report_runs[1]["id"] == result["report_output_run_id"]
    assert report_runs[1]["trigger_type"] == "rerun"
    assert report_runs[1]["status"] == "pending"

    simulation_run = test_db.query(
        "SELECT * FROM simulation_runs WHERE id = ?",
        (result["simulation_run_ids"][0],),
    ).fetchone()
    assert simulation_run["report_output_run_id"] == result["report_output_run_id"]
    assert simulation_run["input_position"] == 1


def test_create_report_rerun_via_legacy_id_creates_canonical_linked_runs(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="household_route_legacy_rerun",
        population_type="household",
        policy_id=77,
    )
    canonical_report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=simulation["id"],
        simulation_2_id=None,
        year="2026",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=canonical_report["id"],
        status="complete",
        output=json.dumps({"result": "canonical"}),
    )
    report_output_id_map_service.set_mapping(
        legacy_report_output_id=3001,
        canonical_report_output_id=canonical_report["id"],
    )

    client = create_test_client()
    response = client.post("/us/report/3001/rerun", json={})

    assert response.status_code == 201
    result = response.get_json()["result"]
    assert result["requested_report_output_id"] == 3001
    assert result["report_output_id"] == canonical_report["id"]
    assert len(result["simulation_run_ids"]) == 1

    report_run = test_db.query(
        "SELECT * FROM report_output_runs WHERE id = ?",
        (result["report_output_run_id"],),
    ).fetchone()
    assert report_run["report_output_id"] == canonical_report["id"]
    assert report_run["trigger_type"] == "rerun"

    simulation_run = test_db.query(
        "SELECT * FROM simulation_runs WHERE id = ?",
        (result["simulation_run_ids"][0],),
    ).fetchone()
    assert simulation_run["report_output_run_id"] == result["report_output_run_id"]
    assert simulation_run["input_position"] == 1


def test_create_report_rerun_for_comparison_report_creates_two_linked_simulation_runs(
    test_db,
):
    baseline_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/nc",
        population_type="geography",
        policy_id=81,
    )
    reform_simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/nc",
        population_type="geography",
        policy_id=82,
    )
    report = report_output_service.create_report_output(
        country_id="us",
        simulation_1_id=baseline_simulation["id"],
        simulation_2_id=reform_simulation["id"],
        year="2026",
    )
    report_output_service.update_report_output(
        country_id="us",
        report_id=report["id"],
        status="complete",
        output=json.dumps({"result": "comparison"}),
    )

    client = create_test_client()
    response = client.post(f"/us/report/{report['id']}/rerun", json={})

    assert response.status_code == 201
    result = response.get_json()["result"]
    assert result["report_output_id"] == report["id"]
    assert len(result["simulation_run_ids"]) == 2

    linked_simulation_runs = test_db.query(
        """
        SELECT * FROM simulation_runs
        WHERE report_output_run_id = ?
        ORDER BY input_position
        """,
        (result["report_output_run_id"],),
    ).fetchall()
    assert [run["simulation_id"] for run in linked_simulation_runs] == [
        baseline_simulation["id"],
        reform_simulation["id"],
    ]
    assert [run["input_position"] for run in linked_simulation_runs] == [1, 2]
    assert [run["status"] for run in linked_simulation_runs] == [
        "pending",
        "pending",
    ]


def test_create_report_rerun_rejects_report_with_missing_linked_simulation(test_db):
    test_db.query(
        """
        INSERT INTO report_outputs (
            country_id, simulation_1_id, simulation_2_id, api_version, status, year
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("us", 987654, None, get_report_output_cache_version("us"), "complete", "2026"),
    )
    report = test_db.query(
        "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    client = create_test_client()
    response = client.post(f"/us/report/{report['id']}/rerun", json={})

    assert response.status_code == 400
    assert "Simulation #987654 not found" in response.get_data(as_text=True)

    report_runs = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report["id"],),
    ).fetchall()
    assert report_runs == []


def test_report_rerun_http_lifecycle_patches_linked_runs_and_reads_display(
    test_db,
):
    client = create_test_client()
    simulation_response = client.post(
        "/us/simulation",
        json={
            "population_id": "household_route_http_lifecycle",
            "population_type": "household",
            "policy_id": 83,
        },
    )
    assert simulation_response.status_code == 201
    simulation = simulation_response.get_json()["result"]

    report_response = client.post(
        "/us/report",
        json={
            "simulation_1_id": simulation["id"],
            "simulation_2_id": None,
            "year": "2026",
        },
    )
    assert report_response.status_code == 201
    report = report_response.get_json()["result"]

    initial_patch_response = client.patch(
        "/us/report",
        json={
            "id": report["id"],
            "status": "complete",
            "output": json.dumps({"result": "initial report"}),
        },
    )
    assert initial_patch_response.status_code == 200

    rerun_response = client.post(f"/us/report/{report['id']}/rerun", json={})
    assert rerun_response.status_code == 201
    rerun = rerun_response.get_json()["result"]
    assert len(rerun["simulation_run_ids"]) == 1

    simulation_patch_response = client.patch(
        "/us/simulation",
        json={
            "id": simulation["id"],
            "simulation_run_id": rerun["simulation_run_ids"][0],
            "status": "complete",
            "output": json.dumps({"result": "rerun simulation"}),
        },
    )
    assert simulation_patch_response.status_code == 200

    report_patch_response = client.patch(
        "/us/report",
        json={
            "id": report["id"],
            "report_output_run_id": rerun["report_output_run_id"],
            "status": "complete",
            "output": json.dumps({"result": "rerun report"}),
        },
    )
    assert report_patch_response.status_code == 200

    get_response = client.get(f"/us/report/{report['id']}")
    assert get_response.status_code == 200
    result = get_response.get_json()["result"]
    assert result["id"] == report["id"]
    assert result["status"] == "complete"
    assert result["output"] == json.dumps({"result": "rerun report"})

    report_rows = test_db.query("SELECT * FROM report_outputs").fetchall()
    report_runs = test_db.query(
        "SELECT * FROM report_output_runs WHERE report_output_id = ?",
        (report["id"],),
    ).fetchall()
    linked_simulation_runs = test_db.query(
        """
        SELECT * FROM simulation_runs
        WHERE report_output_run_id = ?
        """,
        (rerun["report_output_run_id"],),
    ).fetchall()
    assert len(report_rows) == 1
    assert len(report_runs) == 2
    assert len(linked_simulation_runs) == 1


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


def test_patch_report_output_rejects_non_string_run_metadata(test_db):
    simulation = simulation_service.create_simulation(
        country_id="us",
        population_id="state/mt",
        population_type="geography",
        policy_id=74,
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
            "policyengine_version": 123,
        },
    )

    assert response.status_code == 400


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


def test_patch_report_output_metadata_only_preserves_stored_explicit_report_spec(
    test_db,
):
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
