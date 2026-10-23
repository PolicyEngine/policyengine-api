"""A complete simulation or report result is final.

``PATCH /{country_id}/simulation`` and ``PATCH /{country_id}/report`` take no
credential: the browser that ran a calculation stores its result, and records
are shared, since identical requests reuse one record. So once a record holds
a complete result, an update may only repeat it (a retried write, or a second
browser finishing the same calculation) and never change it. Changing it
answers 409 and leaves the record as it was.

Two results are not final, because the server, not a caller, decided they run
again: stale SPM output on a simulation, a report stored under an outdated
cache version, and either record while a rerun the server started is pending
or running.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from flask import Flask
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from policyengine_api.data.v1_models import (
    ReportOutput,
    ReportOutputRun,
    Simulation,
    SimulationRun,
)
from policyengine_api.routes.error_routes import error_bp
from policyengine_api.routes.report_output_routes import report_output_bp
from policyengine_api.routes.simulation_routes import simulation_bp
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.report_run_service import (
    NewReportOutputRun,
    ReportRunService,
)
from policyengine_api.services.simulation_run_service import (
    NewSimulationRun,
    SimulationRunService,
)
from policyengine_api.services.simulation_service import SimulationService

SPM_RECEIPT = {
    "schema_version": "canonical-spm-provenance-v2",
    "forecast_id": "canonical-forecast",
    "forecast_sha256": "a" * 64,
    "scenario": "ce_trend",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
    "years": ["2025"],
    "runtime_versions": {
        "policyengine": "6.2.1",
        "policyengine-core": "3.32.10",
        "policyengine-us": "2.2.1",
        "spm-calculator": "1.0.0",
    },
}
HOUSEHOLD_RESULT = {"household": {"people": {"you": {"net_income": {"2026": 1}}}}}
FORGED_RESULT = {"household": {"people": {"you": {"net_income": {"2026": 999}}}}}


def economy_output(budgetary_impact: int) -> dict:
    return {
        "spm_provenance": {
            "schema_version": "canonical-spm-comparison-v2",
            "baseline": {"receipt": SPM_RECEIPT, "execution_count": 2},
            "reform": {"receipt": SPM_RECEIPT, "execution_count": 2},
        },
        "budgetary_impact": budgetary_impact,
    }


@pytest.fixture
def client(orm_session_factory):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(error_bp)
    app.register_blueprint(simulation_bp)
    app.register_blueprint(report_output_bp)
    with (
        patch(
            "policyengine_api.routes.simulation_routes.simulation_service",
            SimulationService(orm_session_factory),
        ),
        patch(
            "policyengine_api.routes.report_output_routes.report_output_service",
            ReportOutputService(orm_session_factory),
        ),
    ):
        yield app.test_client()


def _new_simulation(client, *, population_type="household", population_id=None):
    response = client.post(
        "/us/simulation",
        json={
            "population_id": population_id or f"household-{uuid.uuid4()}",
            "population_type": population_type,
            "policy_id": 1,
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["result"]["id"]


def _new_report(client):
    simulation_id = _new_simulation(client)
    response = client.post("/us/report", json={"simulation_1_id": simulation_id})
    assert response.status_code == 201, response.get_json()
    return response.get_json()["result"]["id"]


def _new_economy_report(client):
    baseline = _new_simulation(client, population_type="geography", population_id="us")
    reform_response = client.post(
        "/us/simulation",
        json={"population_id": "us", "population_type": "geography", "policy_id": 2},
    )
    reform = reform_response.get_json()["result"]["id"]
    response = client.post(
        "/us/report",
        json={"simulation_1_id": baseline, "simulation_2_id": reform, "year": "2025"},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["result"]["id"]


def _patch(client, resource, record_id, **fields):
    return client.patch(f"/us/{resource}", json={"id": record_id, **fields})


def _stored(session_factory, model, record_id):
    with session_factory() as session:
        record = session.get(model, record_id)
        return {
            "status": record.status,
            "output": record.output,
            "error_message": record.error_message,
            "api_version": record.api_version,
        }


def _run_rows(session_factory, model, foreign_key, record_id):
    with session_factory() as session:
        return [
            (run.id, run.status, run.output, run.error_message)
            for run in session.scalars(
                select(model).where(getattr(model, foreign_key) == record_id)
            )
        ]


# Simulations


def test_anonymous_patch_cannot_change_a_complete_simulation(
    client, orm_session_factory
):
    simulation_id = _new_simulation(client)
    assert (
        _patch(
            client,
            "simulation",
            simulation_id,
            status="complete",
            output=json.dumps(HOUSEHOLD_RESULT),
        ).status_code
        == 200
    )
    before = _stored(orm_session_factory, Simulation, simulation_id)
    runs_before = _run_rows(
        orm_session_factory, SimulationRun, "simulation_id", simulation_id
    )

    for attack in (
        {"status": "complete", "output": FORGED_RESULT},
        {"output": FORGED_RESULT},
        {"status": "error", "error_message": "attacker-controlled failure"},
        {"error_message": "attacker-controlled note"},
        {"status": "pending"},
    ):
        response = _patch(client, "simulation", simulation_id, **attack)

        assert response.status_code == 409, attack
        body = response.get_json()
        assert body["status"] == "error"
        assert "is complete; its result cannot be changed" in body["message"]
        assert _stored(orm_session_factory, Simulation, simulation_id) == before
        assert (
            _run_rows(
                orm_session_factory, SimulationRun, "simulation_id", simulation_id
            )
            == runs_before
        )

    read = client.get(f"/us/simulation/{simulation_id}").get_json()["result"]
    assert json.loads(read["output"]) == HOUSEHOLD_RESULT


def test_calculation_path_completes_and_may_repeat_its_result(
    client, orm_session_factory
):
    simulation_id = _new_simulation(client)

    completed = _patch(
        client,
        "simulation",
        simulation_id,
        status="complete",
        output=json.dumps(HOUSEHOLD_RESULT),
    )
    stored = _stored(orm_session_factory, Simulation, simulation_id)
    # A retry, or a second browser that ran the same calculation, sends the
    # same result again; either JSON encoding of it is a repeat.
    repeats = [
        _patch(
            client,
            "simulation",
            simulation_id,
            status="complete",
            output=output,
        )
        for output in (json.dumps(HOUSEHOLD_RESULT), HOUSEHOLD_RESULT)
    ]

    assert completed.status_code == 200
    assert stored["status"] == "complete"
    assert stored["output"] == HOUSEHOLD_RESULT
    for repeat in repeats:
        assert repeat.status_code == 200
        assert json.loads(repeat.get_json()["result"]["output"]) == HOUSEHOLD_RESULT
    assert _stored(orm_session_factory, Simulation, simulation_id) == stored


def test_failed_simulation_can_be_calculated_again(client, orm_session_factory):
    simulation_id = _new_simulation(client)

    failed = _patch(
        client, "simulation", simulation_id, status="error", error_message="timeout"
    )
    completed = _patch(
        client, "simulation", simulation_id, status="complete", output=HOUSEHOLD_RESULT
    )

    assert failed.status_code == 200
    assert completed.status_code == 200
    stored = _stored(orm_session_factory, Simulation, simulation_id)
    assert stored["status"] == "complete"
    assert stored["output"] == HOUSEHOLD_RESULT


def test_stale_spm_simulation_output_is_not_final(client, orm_session_factory):
    with orm_session_factory.begin() as session:
        simulation = Simulation(
            country_id="us",
            population_id="household-stale",
            population_type="household",
            policy_id=1,
            api_version="historical",
            status="complete",
            output={"household": {}, "spm_config": {"geography_kind": "national"}},
        )
        session.add(simulation)
        session.flush()
        simulation_id = simulation.id

    response = _patch(
        client, "simulation", simulation_id, status="complete", output=HOUSEHOLD_RESULT
    )

    assert response.status_code == 200
    assert (
        _stored(orm_session_factory, Simulation, simulation_id)["output"]
        == HOUSEHOLD_RESULT
    )


def test_server_started_simulation_rerun_is_not_final(client, orm_session_factory):
    simulation_id = _new_simulation(client)
    _patch(
        client, "simulation", simulation_id, status="complete", output=HOUSEHOLD_RESULT
    )
    with orm_session_factory.begin() as session:
        rerun = SimulationRunService().create_simulation_run(
            session, simulation_id, NewSimulationRun(trigger_type="rerun")
        )
        session.get(Simulation, simulation_id).active_run_id = rerun.id

    response = _patch(
        client, "simulation", simulation_id, status="complete", output=FORGED_RESULT
    )

    assert response.status_code == 200
    assert (
        _stored(orm_session_factory, Simulation, simulation_id)["output"]
        == FORGED_RESULT
    )


# Reports


def test_anonymous_patch_cannot_change_a_complete_report(client, orm_session_factory):
    report_id = _new_report(client)
    assert (
        _patch(
            client,
            "report",
            report_id,
            status="complete",
            output=json.dumps({"household": 1}),
        ).status_code
        == 200
    )
    before = _stored(orm_session_factory, ReportOutput, report_id)
    runs_before = _run_rows(
        orm_session_factory, ReportOutputRun, "report_output_id", report_id
    )

    for attack in (
        {"status": "complete", "output": {"household": 2}},
        {"status": "error", "error_message": "attacker-controlled failure"},
        {"status": "running"},
        {"status": "pending"},
        {"output": {"household": 2}},
    ):
        response = _patch(client, "report", report_id, **attack)

        assert response.status_code == 409, attack
        assert (
            "is complete; its result cannot be changed"
            in (response.get_json()["message"])
        )
        assert _stored(orm_session_factory, ReportOutput, report_id) == before
        assert (
            _run_rows(
                orm_session_factory, ReportOutputRun, "report_output_id", report_id
            )
            == runs_before
        )

    repeat = _patch(
        client, "report", report_id, status="complete", output={"household": 1}
    )
    assert repeat.status_code == 200
    assert _stored(orm_session_factory, ReportOutput, report_id) == before


def test_completed_us_economy_report_compares_its_canonical_result(
    client, orm_session_factory
):
    report_id = _new_economy_report(client)

    completed = _patch(
        client, "report", report_id, status="complete", output=economy_output(42)
    )
    repeated = _patch(
        client,
        "report",
        report_id,
        status="complete",
        output=json.dumps(economy_output(42)),
    )
    changed = _patch(
        client, "report", report_id, status="complete", output=economy_output(43)
    )

    assert completed.status_code == 200
    assert repeated.status_code == 200
    assert changed.status_code == 409
    assert _stored(orm_session_factory, ReportOutput, report_id)["output"] == (
        economy_output(42)
    )


def test_report_under_an_outdated_cache_version_is_not_final(
    client, orm_session_factory
):
    report_id = _new_report(client)
    _patch(client, "report", report_id, status="complete", output={"household": 1})
    with orm_session_factory.begin() as session:
        session.get(ReportOutput, report_id).api_version = "outdated"

    response = _patch(
        client, "report", report_id, status="complete", output={"household": 2}
    )

    assert response.status_code == 200
    assert _stored(orm_session_factory, ReportOutput, report_id)["output"] == {
        "household": 2
    }


def test_server_started_report_rerun_is_not_final(client, orm_session_factory):
    report_id = _new_report(client)
    _patch(client, "report", report_id, status="complete", output={"household": 1})
    with orm_session_factory.begin() as session:
        rerun = ReportRunService().create_report_output_run(
            session, report_id, NewReportOutputRun(trigger_type="rerun")
        )
        session.get(ReportOutput, report_id).active_run_id = rerun.id

    running = _patch(client, "report", report_id, status="running")
    completed = _patch(
        client, "report", report_id, status="complete", output={"household": 2}
    )

    assert running.status_code == 200
    assert completed.status_code == 200
    assert _stored(orm_session_factory, ReportOutput, report_id)["output"] == {
        "household": 2
    }


# Properties over every update sequence


_OUTPUTS = (
    {"value": 1},
    {"value": 2},
    {"nested": {"values": [1, 2.5, None]}},
)
_output_values = st.one_of(
    st.none(),
    st.sampled_from(_OUTPUTS),
    st.sampled_from(_OUTPUTS).map(json.dumps),
)


def _update(statuses):
    return st.fixed_dictionaries(
        {},
        optional={
            "status": st.one_of(st.none(), st.sampled_from(statuses)),
            "output": _output_values,
            "error_message": st.one_of(st.none(), st.sampled_from(["a", "b"])),
        },
    )


def _updates(statuses):
    """Any updates, then a completion, then any updates or repeats of it."""

    @st.composite
    def sequences(draw):
        completion = {
            "status": "complete",
            "output": draw(st.sampled_from(_OUTPUTS)),
        }
        later = st.one_of(
            _update(statuses),
            st.just(completion),
            st.just({**completion, "output": json.dumps(completion["output"])}),
        )
        return [
            *draw(st.lists(_update(statuses), max_size=5)),
            completion,
            *draw(st.lists(later, max_size=6)),
        ]

    return sequences()


def _decoded(output):
    return json.loads(output) if isinstance(output, str) else output


def _expected_response(model, update, *, running_allowed):
    """Return the status code and next record state the route should produce."""
    values = {key: value for key, value in update.items() if value is not None}
    if "output" in values:
        values["output"] = _decoded(values["output"])
    if values.get("status") == "complete" and "output" not in values:
        return 400, model
    if not values:
        return 400, model
    if model["status"] == "complete":
        changed = any(model[field] != value for field, value in values.items())
        return (409 if changed else 200), model
    if values.get("status") == "running" and not running_allowed(model):
        return 400, model
    return 200, {**model, **values}


@dataclass(frozen=True)
class _UpdatedResource:
    """A PATCH route, its record model and when its records may be marked running."""

    path: str
    model: type
    running_allowed: Callable[[dict], bool]


SIMULATIONS = _UpdatedResource("simulation", Simulation, lambda _record: False)
# A report's one run mirrors its status, so it can be marked running only while
# that run is still pending or running.
REPORTS = _UpdatedResource(
    "report",
    ReportOutput,
    lambda record: record["status"] in {"pending", "running"},
)


def _check_update_sequence(client, session_factory, resource, record_id, updates):
    model = {"status": "pending", "output": None, "error_message": None}
    completed_record = None
    for update in updates:
        response = _patch(client, resource.path, record_id, **update)
        expected_code, model = _expected_response(
            model, update, running_allowed=resource.running_allowed
        )
        stored = _stored(session_factory, resource.model, record_id)

        assert response.status_code == expected_code, (update, response.get_json())
        assert {field: stored[field] for field in model} == model
        if completed_record is not None:
            # Once complete, nothing an update sends changes the record.
            assert stored == completed_record
        elif stored["status"] == "complete":
            completed_record = stored
            event(f"{resource.path} completed")


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(updates=_updates(["pending", "complete", "error"]))
def test_every_simulation_update_sequence_keeps_a_complete_result(
    client, orm_session_factory, updates
):
    _check_update_sequence(
        client, orm_session_factory, SIMULATIONS, _new_simulation(client), updates
    )


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(updates=_updates(["pending", "running", "complete", "error"]))
def test_every_report_update_sequence_keeps_a_complete_result(
    client, orm_session_factory, updates
):
    _check_update_sequence(
        client, orm_session_factory, REPORTS, _new_report(client), updates
    )
