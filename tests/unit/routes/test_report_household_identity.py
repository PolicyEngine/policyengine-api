"""Report linkage preserves historical US household identity and saved spelling."""

import json

from flask import Flask
import pytest
from sqlalchemy import select

from policyengine_api.data.v1_models import (
    Household,
    ReportOutput,
    ReportOutputRun,
    Simulation,
)
from policyengine_api.routes import report_output_routes, simulation_routes
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.report_spec_service import ReportSpecService
from policyengine_api.services.simulation_service import SimulationService


def test_historical_baseline_and_new_reform_persist_complete_comparison_report(
    monkeypatch, orm_session_factory
):
    historical_output = {"household": {"people": {"you": {"age": {"2026": 40}}}}}
    with orm_session_factory.begin() as session:
        session.add(
            Household(
                id=1,
                country_id="us",
                api_version="historical",
                household_json=historical_output["household"],
                household_hash="historical-household-1",
            )
        )
        baseline = Simulation(
            country_id="us",
            population_id="00001",
            population_type="household",
            policy_id=1,
            api_version="historical",
            status="complete",
            output=historical_output,
        )
        session.add(baseline)
        session.flush()
        baseline_id = baseline.id

    monkeypatch.setattr(
        simulation_routes, "simulation_service", SimulationService(orm_session_factory)
    )
    monkeypatch.setattr(
        report_output_routes,
        "report_output_service",
        ReportOutputService(orm_session_factory),
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(simulation_routes.simulation_bp)
    app.register_blueprint(report_output_routes.report_output_bp)
    client = app.test_client()

    replay = client.post(
        "/us/simulation",
        json={"population_id": "00001", "population_type": "household", "policy_id": 1},
    )
    assert replay.status_code == 200, replay.json
    assert replay.json["result"]["id"] == baseline_id
    assert replay.json["result"]["population_id"] == "00001"
    assert replay.json["result"]["status"] == "complete"
    assert json.loads(replay.json["result"]["output"]) == historical_output

    reform = client.post(
        "/us/simulation",
        json={"population_id": "00001", "population_type": "household", "policy_id": 2},
    )
    assert reform.status_code == 201, reform.json
    reform_id = reform.json["result"]["id"]
    assert reform_id != baseline_id
    assert reform.json["result"]["population_id"] == "1"
    assert reform.json["result"]["status"] == "pending"

    payload = {
        "simulation_1_id": baseline_id,
        "simulation_2_id": reform_id,
        "year": "2026",
    }
    expected_spec = {
        "country_id": "us",
        "report_kind": "household_comparison",
        "time_period": "2026",
        "simulation_1": {
            "population_type": "household",
            "population_id": "00001",
            "policy_id": 1,
        },
        "simulation_2": {
            "population_type": "household",
            "population_id": "1",
            "policy_id": 2,
        },
    }
    created = client.post("/us/report", json=payload)
    assert created.status_code == 201, created.json
    report_id = created.json["result"]["id"]
    replayed = client.post("/us/report", json=payload)
    retrieved = client.get(f"/us/report/{report_id}")
    assert replayed.status_code == retrieved.status_code == 200
    for response in (created, replayed, retrieved):
        result = response.json["result"]
        assert result["id"] == report_id
        assert result["report_kind"] == "household_comparison"
        assert result["report_spec_json"] == expected_spec
        assert result["report_spec_schema_version"] == 1
        assert result["report_spec_status"] == "explicit"
        assert result["status"] == "pending"

    with orm_session_factory() as session:
        saved_baseline = session.get(Simulation, baseline_id)
        saved_reform = session.get(Simulation, reform_id)
        assert saved_baseline.population_id == "00001"
        assert saved_baseline.output == historical_output
        assert saved_baseline.simulation_spec_json["population_id"] == "00001"
        assert saved_reform.population_id == "1"
        assert saved_reform.simulation_spec_json["population_id"] == "1"
        saved_report = session.get(ReportOutput, report_id)
        assert saved_report.report_kind == "household_comparison"
        assert saved_report.report_spec_json == expected_spec
        assert saved_report.report_spec_schema_version == 1
        assert saved_report.report_spec_status == "explicit"
        runs = list(
            session.scalars(
                select(ReportOutputRun).where(
                    ReportOutputRun.report_output_id == report_id
                )
            )
        )
        assert len(runs) == 1
        assert saved_report.active_run_id == runs[0].id
        assert runs[0].report_spec_snapshot_json == expected_spec
        assert runs[0].status == "pending"


def comparison_models(country_id, population_type, first_id, second_id):
    first = Simulation(
        id=1,
        country_id=country_id,
        population_type=population_type,
        population_id=first_id,
        policy_id=1,
    )
    second = Simulation(
        id=2,
        country_id=country_id,
        population_type=population_type,
        population_id=second_id,
        policy_id=2,
    )
    report = ReportOutput(
        country_id=country_id, simulation_1_id=1, simulation_2_id=2, year="2026"
    )
    return report, first, second


@pytest.mark.parametrize(
    "unrelated_id", ["1suffix", "1.0", "+1", "1\n", "١", "１", "2"]
)
def test_household_report_does_not_alias_nonnumeric_or_different_ids(unrelated_id):
    models = comparison_models("us", "household", "00001", unrelated_id)
    with pytest.raises(ValueError, match="matching household IDs"):
        ReportSpecService().build_report_spec(*models)


@pytest.mark.parametrize(
    "country_id,population_type",
    [("uk", "household"), ("us", "geography"), ("uk", "geography")],
)
def test_numeric_report_aliases_are_limited_to_us_households(
    country_id, population_type
):
    models = comparison_models(country_id, population_type, "00001", "1")
    with pytest.raises(ValueError, match="require matching"):
        ReportSpecService().build_report_spec(*models)


@pytest.mark.parametrize(
    "population_id", ["household-1", "1suffix", "1.0", "+1", "1\n", "١", "１"]
)
def test_matching_literal_household_ids_retain_saved_spelling(population_id):
    models = comparison_models("us", "household", population_id, population_id)
    spec = ReportSpecService().build_report_spec(*models)
    assert spec.simulation_1.population_id == population_id
    assert spec.simulation_2.population_id == population_id
