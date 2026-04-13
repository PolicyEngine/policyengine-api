import pytest
from flask import Flask

from policyengine_api.constants import (
    get_economy_impact_cache_version,
    get_report_output_cache_version,
)
from policyengine_api.routes.error_routes import error_bp
from policyengine_api.routes.report_output_routes import report_output_bp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(error_bp)
    app.register_blueprint(report_output_bp)

    with app.test_client() as test_client:
        yield test_client


def insert_simulation(
    test_db,
    *,
    country_id="us",
    api_version="0.0.0",
    population_id="household_1",
    population_type="household",
    policy_id=1,
    status="complete",
    output='{"result": true}',
    error_message="old error",
):
    test_db.query(
        """INSERT INTO simulations
        (country_id, api_version, population_id, population_type, policy_id, status, output, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            country_id,
            api_version,
            population_id,
            population_type,
            policy_id,
            status,
            output,
            error_message,
        ),
    )
    return test_db.query(
        "SELECT * FROM simulations ORDER BY id DESC LIMIT 1"
    ).fetchone()


def insert_report_output(
    test_db,
    *,
    country_id="us",
    simulation_1_id,
    simulation_2_id=None,
    status="complete",
    output='{"report": true}',
    error_message="old error",
    year="2025",
):
    test_db.query(
        """INSERT INTO report_outputs
        (country_id, simulation_1_id, simulation_2_id, api_version, status, output, error_message, year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            country_id,
            simulation_1_id,
            simulation_2_id,
            get_report_output_cache_version(country_id),
            status,
            output,
            error_message,
            year,
        ),
    )
    return test_db.query(
        "SELECT * FROM report_outputs ORDER BY id DESC LIMIT 1"
    ).fetchone()


def insert_reform_impact(
    test_db,
    *,
    baseline_policy_id,
    reform_policy_id,
    country_id="us",
    region="us",
    dataset="default",
    time_period="2025",
    options_json="[]",
    options_hash="[]",
    api_version=None,
    reform_impact_json='{"impact": 1}',
    status="ok",
    message="Completed",
    execution_id="exec-1",
):
    if api_version is None:
        api_version = get_economy_impact_cache_version(country_id)

    test_db.query(
        """INSERT INTO reform_impact
        (baseline_policy_id, reform_policy_id, country_id, region, dataset, time_period,
        options_json, options_hash, api_version, reform_impact_json, status, message, start_time,
        execution_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
        (
            baseline_policy_id,
            reform_policy_id,
            country_id,
            region,
            dataset,
            time_period,
            options_json,
            options_hash,
            api_version,
            reform_impact_json,
            status,
            message,
            execution_id,
        ),
    )


def test_rerun_report_output_resets_household_report_and_simulation(client, test_db):
    simulation = insert_simulation(test_db)
    report_output = insert_report_output(test_db, simulation_1_id=simulation["id"])

    response = client.post(f"/us/report/{report_output['id']}/rerun")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["result"] == {
        "report_id": report_output["id"],
        "report_type": "household",
        "simulation_ids": [simulation["id"]],
        "economy_cache_rows_deleted": 0,
    }

    reset_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?", (report_output["id"],)
    ).fetchone()
    assert reset_report["status"] == "pending"
    assert reset_report["output"] is None
    assert reset_report["error_message"] is None

    reset_simulation = test_db.query(
        "SELECT * FROM simulations WHERE id = ?", (simulation["id"],)
    ).fetchone()
    assert reset_simulation["status"] == "pending"
    assert reset_simulation["output"] is None
    assert reset_simulation["error_message"] is None


def test_rerun_report_output_resets_household_comparison_report_and_both_simulations(
    client, test_db
):
    baseline_simulation = insert_simulation(
        test_db,
        population_id="household_baseline",
        policy_id=20,
    )
    reform_simulation = insert_simulation(
        test_db,
        population_id="household_reform",
        policy_id=21,
        output='{"result": "comparison"}',
    )
    report_output = insert_report_output(
        test_db,
        simulation_1_id=baseline_simulation["id"],
        simulation_2_id=reform_simulation["id"],
    )

    response = client.post(f"/us/report/{report_output['id']}/rerun")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["result"] == {
        "report_id": report_output["id"],
        "report_type": "household",
        "simulation_ids": [baseline_simulation["id"], reform_simulation["id"]],
        "economy_cache_rows_deleted": 0,
    }

    for simulation_id in (baseline_simulation["id"], reform_simulation["id"]):
        reset_simulation = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation_id,),
        ).fetchone()
        assert reset_simulation["status"] == "pending"
        assert reset_simulation["output"] is None
        assert reset_simulation["error_message"] is None


def test_rerun_report_output_resets_economy_report_and_purges_cache(client, test_db):
    baseline_simulation = insert_simulation(
        test_db,
        population_id="state/ca",
        population_type="geography",
        policy_id=10,
    )
    reform_simulation = insert_simulation(
        test_db,
        population_id="state/ca",
        population_type="geography",
        policy_id=11,
        output='{"result": "reform"}',
    )
    report_output = insert_report_output(
        test_db,
        simulation_1_id=baseline_simulation["id"],
        simulation_2_id=reform_simulation["id"],
    )

    current_version = get_economy_impact_cache_version("us")
    insert_reform_impact(
        test_db,
        baseline_policy_id=10,
        reform_policy_id=11,
        region="state/ca",
        api_version=current_version,
        execution_id="exec-current",
    )
    insert_reform_impact(
        test_db,
        baseline_policy_id=10,
        reform_policy_id=11,
        region="state/ca",
        api_version="e1stale01",
        execution_id="exec-stale",
    )
    insert_reform_impact(
        test_db,
        baseline_policy_id=10,
        reform_policy_id=11,
        region="state/ca",
        dataset="enhanced_cps",
        api_version=current_version,
        execution_id="exec-other-dataset",
    )

    response = client.post(f"/us/report/{report_output['id']}/rerun")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["result"] == {
        "report_id": report_output["id"],
        "report_type": "geography",
        "simulation_ids": [baseline_simulation["id"], reform_simulation["id"]],
        "economy_cache_rows_deleted": 1,
    }

    remaining_reform_impacts = test_db.query(
        "SELECT execution_id FROM reform_impact ORDER BY execution_id"
    ).fetchall()
    assert [row["execution_id"] for row in remaining_reform_impacts] == [
        "exec-other-dataset",
        "exec-stale",
    ]


def test_rerun_report_output_single_simulation_economy_uses_baseline_policy_for_cache_key(
    client, test_db
):
    simulation = insert_simulation(
        test_db,
        population_id="state/ny",
        population_type="geography",
        policy_id=30,
    )
    report_output = insert_report_output(test_db, simulation_1_id=simulation["id"])

    current_version = get_economy_impact_cache_version("us")
    insert_reform_impact(
        test_db,
        baseline_policy_id=30,
        reform_policy_id=30,
        region="state/ny",
        api_version=current_version,
        execution_id="exec-matching",
    )
    insert_reform_impact(
        test_db,
        baseline_policy_id=30,
        reform_policy_id=31,
        region="state/ny",
        api_version=current_version,
        execution_id="exec-other-policy",
    )

    response = client.post(f"/us/report/{report_output['id']}/rerun")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["result"] == {
        "report_id": report_output["id"],
        "report_type": "geography",
        "simulation_ids": [simulation["id"]],
        "economy_cache_rows_deleted": 1,
    }

    remaining_reform_impacts = test_db.query(
        "SELECT execution_id FROM reform_impact ORDER BY execution_id"
    ).fetchall()
    assert [row["execution_id"] for row in remaining_reform_impacts] == [
        "exec-other-policy"
    ]


def test_rerun_report_output_missing_report_returns_404(client):
    response = client.post("/us/report/999/rerun")

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["result"] is None
    assert "Report #999 not found." in payload["message"]


def test_rerun_report_output_missing_linked_simulation_returns_400(client, test_db):
    report_output = insert_report_output(test_db, simulation_1_id=999)

    response = client.post(f"/us/report/{report_output['id']}/rerun")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["result"] is None
    assert "references simulation #999" in payload["message"]

    unchanged_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?", (report_output["id"],)
    ).fetchone()
    assert unchanged_report["status"] == "complete"
    assert unchanged_report["output"] == '{"report": true}'


def test_rerun_report_output_missing_secondary_simulation_does_not_partially_reset(
    client, test_db
):
    baseline_simulation = insert_simulation(
        test_db,
        population_id="household_baseline",
        policy_id=40,
    )
    report_output = insert_report_output(
        test_db,
        simulation_1_id=baseline_simulation["id"],
        simulation_2_id=999,
    )

    response = client.post(f"/us/report/{report_output['id']}/rerun")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "references simulation #999" in payload["message"]

    unchanged_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?", (report_output["id"],)
    ).fetchone()
    assert unchanged_report["status"] == "complete"
    assert unchanged_report["output"] == '{"report": true}'
    assert unchanged_report["error_message"] == "old error"

    unchanged_simulation = test_db.query(
        "SELECT * FROM simulations WHERE id = ?", (baseline_simulation["id"],)
    ).fetchone()
    assert unchanged_simulation["status"] == "complete"
    assert unchanged_simulation["output"] == '{"result": true}'
    assert unchanged_simulation["error_message"] == "old error"


def test_rerun_report_output_mismatched_population_types_returns_controlled_error(
    client, test_db
):
    geography_simulation = insert_simulation(
        test_db,
        population_id="state/tx",
        population_type="geography",
        policy_id=50,
    )
    household_simulation = insert_simulation(
        test_db,
        population_id="household_mismatch",
        population_type="household",
        policy_id=51,
        output='{"result": "mismatch"}',
    )
    report_output = insert_report_output(
        test_db,
        simulation_1_id=geography_simulation["id"],
        simulation_2_id=household_simulation["id"],
    )

    response = client.post(f"/us/report/{report_output['id']}/rerun")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "mismatched population types" in payload["message"]

    unchanged_report = test_db.query(
        "SELECT * FROM report_outputs WHERE id = ?", (report_output["id"],)
    ).fetchone()
    assert unchanged_report["status"] == "complete"
    assert unchanged_report["output"] == '{"report": true}'
    assert unchanged_report["error_message"] == "old error"

    for simulation_id, expected_output in (
        (geography_simulation["id"], '{"result": true}'),
        (household_simulation["id"], '{"result": "mismatch"}'),
    ):
        unchanged_simulation = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation_id,),
        ).fetchone()
        assert unchanged_simulation["status"] == "complete"
        assert unchanged_simulation["output"] == expected_output
