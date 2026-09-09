"""Simulation records must not silently discard independent SPM overrides."""

import json
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import func, select

from policyengine_api.data.v1_models import Simulation, SimulationRun
from policyengine_api.routes.simulation_routes import simulation_bp
from policyengine_api.services.simulation_service import SimulationService


@pytest.mark.parametrize("country_id", ["us", "uk"])
@pytest.mark.parametrize("spm", [None, {}, {"geography_kind": "national"}])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_simulation_records_reject_spm_overrides_before_read_or_write(
    country_id, spm, method
):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(simulation_bp)
    payload = {"spm": spm}
    if method == "POST":
        payload.update(population_id="1", population_type="household", policy_id=1)
    else:
        payload.update(id=1, status="complete", output={})

    with patch(
        "policyengine_api.routes.simulation_routes.simulation_service"
    ) as service:
        response = app.test_client().open(
            f"/{country_id}/simulation", method=method, json=payload
        )

    assert response.status_code == 400
    result = response.get_json()
    assert result["status"] == "error"
    assert result["result"] is None
    assert result["errors"] == [
        {"code": "SPM_SETTINGS_UNSUPPORTED", "message": result["message"]}
    ]
    assert "linked household" in result["message"]
    assert not service.mock_calls


@pytest.mark.parametrize("population_id", ["00001", "1", "0000001", 1])
def test_repost_historical_numeric_household_alias_replays_completed_output(
    orm_session_factory, population_id
):
    output = {"household": {"people": {}}, "spm_config": {"geography_kind": "national"}}
    with orm_session_factory.begin() as session:
        historical = Simulation(
            country_id="us",
            population_id="00001",
            population_type="household",
            policy_id=1,
            api_version="historical",
            status="complete",
            output=output,
        )
        session.add(historical)
        session.flush()
        historical_id = historical.id

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(simulation_bp)
    service = SimulationService(orm_session_factory)
    with patch("policyengine_api.routes.simulation_routes.simulation_service", service):
        for _ in range(2):
            response = app.test_client().post(
                "/us/simulation",
                json={
                    "population_id": population_id,
                    "population_type": "household",
                    "policy_id": 1,
                },
            )
            assert response.status_code == 200
            result = response.get_json()["result"]
            assert result["id"] == historical_id
            assert result["status"] == "complete"
            assert json.loads(result["output"]) == output
            assert result["population_id"] == "00001"
            assert (
                json.loads(result["simulation_spec_json"])["population_id"] == "00001"
            )

    with orm_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Simulation)) == 1
        run = session.scalar(select(SimulationRun))
        assert run.status == "complete"
        assert run.output == output
        assert run.simulation_spec_snapshot_json["population_id"] == "00001"
