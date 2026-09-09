"""Immutable households retain strict numeric simulation alias boundaries."""

from copy import deepcopy
import json

from flask import Flask
import pytest

from policyengine_api.data.v1_models import Simulation, SimulationRun
from policyengine_api.routes import household_routes, simulation_routes
from policyengine_api.services import household_service
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.simulation_service import SimulationService


INPUTS = {"people": {"you": {"age": {"2026": 40}}}}
NATIONAL = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}


@pytest.fixture
def household_identity_client(monkeypatch, orm_session_factory):
    # Only certification is substituted. HTTP, services, SQL and transactions
    # execute normally against the isolated in-memory ORM fixture.
    def normalize(country_id, selection):
        assert country_id == "us"
        return {**NATIONAL, **(selection or {})}

    monkeypatch.setattr(household_service, "normalize_spm_selection", normalize)
    monkeypatch.setattr(
        household_routes, "household_service", HouseholdService(orm_session_factory)
    )
    monkeypatch.setattr(
        simulation_routes,
        "simulation_service",
        SimulationService(orm_session_factory),
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(household_routes.household_bp)
    app.register_blueprint(simulation_routes.simulation_bp)
    client = app.test_client()
    created = client.post(
        "/us/household",
        json={
            "data": INPUTS,
            "label": "Original",
            "spm": {"geography_kind": "national"},
        },
    )
    assert created.status_code == 201, created.json
    return client, created.json["result"]["household_id"]


@pytest.mark.parametrize(
    "spelling",
    [
        "{id}suffix",
        "{id}.0",
        "+{id}",
        " {id}",
        "{id} ",
        "{id}\n",
        "arabic",
        "fullwidth",
    ],
    ids=[
        "suffix",
        "decimal",
        "plus",
        "leading-space",
        "trailing-space",
        "newline",
        "arabic-digits",
        "fullwidth-digits",
    ],
)
def test_opaque_simulation_identity_stays_distinct_for_immutable_household(
    household_identity_client, spelling
):
    client, household_id = household_identity_client
    url = f"/us/household/{household_id}"
    original = client.get(url).json["result"]
    changed = deepcopy(INPUTS)
    changed["people"]["you"]["age"]["2026"] = 41
    control = client.put(url, json={"data": changed, "label": "Before simulation"})
    assert control.status_code == 405

    if spelling in {"arabic", "fullwidth"}:
        digits = "٠١٢٣٤٥٦٧٨٩" if spelling == "arabic" else "０１２３４５６７８９"
        population_id = str(household_id).translate(str.maketrans("0123456789", digits))
    else:
        population_id = spelling.format(id=household_id)
    simulation = client.post(
        "/us/simulation",
        json={
            "population_id": population_id,
            "population_type": "household",
            "policy_id": 1,
        },
    )
    assert simulation.status_code == 201, simulation.json
    simulation_id = simulation.json["result"]["id"]
    assert simulation.json["result"]["population_id"] == population_id

    changed["people"]["you"]["age"]["2026"] = 42
    response = client.put(url, json={"data": changed, "label": "After simulation"})
    assert response.status_code == 405
    assert client.get(url).json["result"] == original

    saved = client.get(f"/us/simulation/{simulation_id}").json["result"]
    assert saved["population_id"] == population_id
    assert json.loads(saved["simulation_spec_json"])["population_id"] == population_id

    canonical = client.post(
        "/us/simulation",
        json={
            "population_id": str(household_id),
            "population_type": "household",
            "policy_id": 1,
        },
    )
    assert canonical.status_code == 201, canonical.json
    canonical_id = canonical.json["result"]["id"]
    assert canonical_id != simulation_id
    assert canonical.json["result"]["population_id"] == str(household_id)

    opaque_replay = client.post(
        "/us/simulation",
        json={
            "population_id": population_id,
            "population_type": "household",
            "policy_id": 1,
        },
    )
    assert opaque_replay.status_code == 200, opaque_replay.json
    assert opaque_replay.json["result"]["id"] == simulation_id
    assert opaque_replay.json["result"]["population_id"] == population_id
    assert (
        json.loads(opaque_replay.json["result"]["simulation_spec_json"])[
            "population_id"
        ]
        == population_id
    )

    numeric_replay = client.post(
        "/us/simulation",
        json={
            "population_id": str(household_id).zfill(5),
            "population_type": "household",
            "policy_id": 1,
        },
    )
    assert numeric_replay.status_code == 200, numeric_replay.json
    assert numeric_replay.json["result"]["id"] == canonical_id
    assert numeric_replay.json["result"]["population_id"] == str(household_id)


@pytest.mark.parametrize("reference", ["plain", "new-padded", "historical-padded"])
@pytest.mark.parametrize("change", ["inputs", "selection"])
def test_numeric_link_preserves_immutable_household_and_saved_simulation(
    household_identity_client, orm_session_factory, reference, change
):
    client, household_id = household_identity_client
    url = f"/us/household/{household_id}"
    original = client.get(url).json["result"]
    population_id = (
        str(household_id) if reference == "plain" else str(household_id).zfill(5)
    )
    output = {"result": deepcopy(INPUTS), "spm_config": deepcopy(NATIONAL)}
    if reference == "historical-padded":
        with orm_session_factory.begin() as session:
            session.add(
                Simulation(
                    country_id="us",
                    population_id=population_id,
                    population_type="household",
                    policy_id=1,
                    api_version="historical",
                    status="complete",
                    output=output,
                )
            )

    linked = client.post(
        "/us/simulation",
        json={
            "population_id": population_id,
            "population_type": "household",
            "policy_id": 1,
        },
    )
    assert linked.status_code == (200 if reference == "historical-padded" else 201)
    saved_spelling = (
        population_id if reference == "historical-padded" else str(household_id)
    )
    simulation_id = linked.json["result"]["id"]
    assert linked.json["result"]["population_id"] == saved_spelling

    changed = {"data": deepcopy(INPUTS), "label": "Rejected edit"}
    if change == "inputs":
        changed["data"]["people"]["you"]["age"]["2026"] = 41
    else:
        changed["spm"] = {"geography_kind": "county"}
    rejected = client.put(url, json=changed)
    assert rejected.status_code == 405
    assert client.get(url).json["result"] == original

    renamed = client.put(url, json={"data": INPUTS, "label": "Renamed"})
    assert renamed.status_code == 405
    assert client.get(url).json["result"] == original
    saved = client.get(f"/us/simulation/{simulation_id}").json["result"]
    assert saved["population_id"] == saved_spelling
    assert json.loads(saved["simulation_spec_json"])["population_id"] == saved_spelling
    if reference == "historical-padded":
        assert saved["status"] == "complete"
        assert json.loads(saved["output"]) == output
        with orm_session_factory() as session:
            run = session.get(SimulationRun, saved["latest_successful_run_id"])
            assert run.simulation_spec_snapshot_json["population_id"] == saved_spelling
            assert run.output == output
