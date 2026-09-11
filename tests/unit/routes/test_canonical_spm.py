"""Exercise real HTTP, ORM replay and both cache layers at the country boundary."""

from copy import deepcopy
from types import SimpleNamespace

from flask import Flask
import pytest

from policyengine_api import spm
from policyengine_api.data.v1_models import Household, Policy, Simulation
from policyengine_api.extensions import cache
from policyengine_api.routes import household_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_traces import HouseholdTraceCache
from policyengine_api.services.household_calculation_service import (
    CalculationResult,
    HouseholdCalculationService,
)
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.simulation_service import SimulationService


HOUSEHOLD = {"people": {"you": {"age": {"2026": 40}}}}
FORECAST_HASH = "a" * 64


class CountryInputError(ValueError):
    """The public ValueError/code/to_dict protocol used by country packages."""

    def __init__(self, code):
        self.code = code
        super().__init__("An explicit household input is required")

    def to_dict(self):
        return {"code": self.code, "message": str(self)}


class Country:
    metadata = {
        "variables": {
            "age": {"entity": "person", "definitionPeriod": "year", "name": "age"}
        },
        "entities": {"person": {"plural": "people", "roles": {}}},
        "parameters": {"gov.test.amount": {}},
    }

    def __init__(self):
        self.calls = []
        self.error_code = None

    def calculate(self, household, policy, **kwargs):
        self.calls.append((deepcopy(household), deepcopy(policy), deepcopy(kwargs)))
        if self.error_code:
            raise CountryInputError(self.error_code)
        config = kwargs.get("spm")
        receipt = (
            None
            if config is None
            else {
                "forecast_id": "test-artifact",
                "forecast_sha256": config["forecast_content_sha256"],
                "scenario": config["scenario"],
                "geography_kind": config["geography_kind"],
                "runtime_versions": {"policyengine-us": "test-only"},
                "years": {"2026": {"status": "forecast"}},
                "geographies": [],
                "composition_method": "classified-inputs",
                "storage_method": "formula",
            }
        )
        return CalculationResult(household, ["age <2026>"], config, receipt)


@pytest.fixture
def certified(monkeypatch):
    # A test-only certificate/forecast, never a proposed production release pin.
    bundle = {
        "measurements": {
            "spm": {"forecast_content_sha256": FORECAST_HASH, "scenario": "baseline"}
        }
    }
    monkeypatch.setattr(spm, "_current_bundle", lambda: bundle)
    monkeypatch.setattr(spm, "simulation_supports_spm", lambda _: True)
    monkeypatch.setattr(
        spm,
        "_selected_forecast",
        lambda _: SimpleNamespace(
            years=[2022], entry=lambda *a, **k: {}, geography_factor=lambda *a, **k: 1.0
        ),
    )
    return bundle


@pytest.fixture
def harness(monkeypatch, orm_session_factory):
    country = Country()
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=HouseholdTraceCache(
            InMemoryCacheBackend(), CacheNamespace("test", "spm")
        ),
        country_provider=lambda: {"us": country, "uk": country},
    )
    monkeypatch.setattr(household_routes, "household_calculation_service", service)
    monkeypatch.setattr(
        household_routes, "household_service", HouseholdService(orm_session_factory)
    )
    with orm_session_factory.begin() as session:
        session.add_all(
            [
                Policy(
                    id=2,
                    country_id="us",
                    policy_json={},
                    policy_hash="baseline",
                    api_version="test",
                ),
                Policy(
                    id=3,
                    country_id="us",
                    policy_json={"gov.test.amount": {"2026-01-01.2026-12-31": 20}},
                    policy_hash="reform",
                    api_version="test",
                ),
            ]
        )
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="SimpleCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    with app.app_context():
        cache.clear()
    return app.test_client(), country


@pytest.mark.parametrize("code", sorted(spm.SPM_INPUT_ERROR_CODES))
@pytest.mark.parametrize("path", ["/us/calculate", "/us/calculate-full", "stored"])
def test_spm_input_errors_are_structured_400(certified, harness, code, path):
    client, country = harness
    country.error_code = code
    if path == "stored":
        created = client.post(
            "/us/household",
            json={"data": HOUSEHOLD, "spm": {"geography_kind": "national"}},
        )
        household_id = created.json["result"]["household_id"]
        response = client.get(f"/us/household/{household_id}/policy/2")
    else:
        response = client.post(
            path, json={"household": HOUSEHOLD, "spm": {"geography_kind": "national"}}
        )
    assert response.status_code == 400
    assert response.json == {
        "status": "error",
        "result": None,
        "message": "An explicit household input is required",
        "errors": [
            {"code": code, "message": "An explicit household input is required"}
        ],
    }


@pytest.mark.parametrize(
    "selection",
    [
        {"unexpected": True},
        {"geography_kind": "national", "geography_id": "31080"},
        {"geography_kind": "metro"},
        {"forecast_content_sha256": "b" * 64},
        {"county_vintage": "2010"},
        [],
        "national",
    ],
)
@pytest.mark.parametrize("path", ["/us/calculate", "/us/household"])
def test_invalid_settings_never_reach_country_or_storage(
    certified, harness, selection, path
):
    client, country = harness
    response = client.post(
        path, json={"household": HOUSEHOLD, "data": HOUSEHOLD, "spm": selection}
    )
    assert response.status_code == 400
    assert response.json["errors"][0]["code"] == "SPM_SETTINGS_INVALID"
    assert country.calls == []


def test_settings_and_provenance_survive_storage_reform_replay_and_replacement(
    certified, harness
):
    client, country = harness
    response = client.post(
        "/us/household", json={"data": HOUSEHOLD, "spm": {"geography_kind": "national"}}
    )
    assert response.status_code == 201
    household_id = response.json["result"]["household_id"]
    url = f"/us/household/{household_id}"
    stored = client.get(url).json["result"]
    assert stored["spm"]["forecast_content_sha256"] == FORECAST_HASH
    assert stored["household_json"] == HOUSEHOLD

    first = client.get(url + "/policy/2")
    cached = client.get(url + "/policy/2")
    assert first.status_code == cached.status_code == 200
    assert first.json == cached.json
    assert first.json["spm_config"] == stored["spm"]
    assert first.json["spm_provenance"]["forecast_sha256"] == FORECAST_HASH
    assert len(country.calls) == 1
    assert "spm" not in country.calls[0][0]
    assert client.get(url + "/policy/3").status_code == 200
    assert country.calls[1][2]["spm"] == stored["spm"]
    assert country.calls[1][1] != country.calls[0][1]

    # Stage11 households are immutable even before a simulation is linked.
    changed = {"people": {"you": {"age": {"2026": 41}}}}
    assert client.put(url, json={"data": changed}).status_code == 405
    assert client.get(url).json["result"] == stored

    replacement = client.post(
        "/us/household", json={"data": changed, "spm": stored["spm"]}
    )
    assert replacement.status_code == 201
    replacement_id = replacement.json["result"]["household_id"]
    assert replacement_id != household_id
    replacement_url = f"/us/household/{replacement_id}"
    edited = client.get(replacement_url).json["result"]
    assert edited["spm"] == stored["spm"]
    assert edited["household_hash"] != stored["household_hash"]
    assert client.get(replacement_url + "/policy/2").status_code == 200
    assert len(country.calls) == 3

    # Changing only measurement settings creates a distinct immutable identity.
    reselection = client.post(
        "/us/household", json={"data": changed, "spm": {"geography_kind": "county"}}
    )
    assert reselection.status_code == 201
    latest_id = reselection.json["result"]["household_id"]
    latest_url = f"/us/household/{latest_id}"
    latest = client.get(latest_url).json["result"]
    assert latest["household_hash"] != edited["household_hash"]
    assert (
        client.get(latest_url + "/policy/2").json["spm_config"]["geography_kind"]
        == "county"
    )
    assert len(country.calls) == 4
    assert client.get(url).json["result"] == stored
    assert client.get(url + "/policy/2").json == first.json
    assert len(country.calls) == 4


@pytest.mark.parametrize(
    "selection",
    [
        {"geography_kind": "county"},
        {"scenario": "alternative"},
        {"geography_kind": "metro", "geography_id": "31080"},
        {"as_of": "2026-09-09"},
    ],
)
def test_http_cache_varies_with_measurement_settings(certified, harness, selection):
    client, country = harness
    payload = {"household": HOUSEHOLD, "spm": {"geography_kind": "national"}}
    first = client.post("/us/calculate", json=payload)
    assert first.status_code == 200
    assert client.post("/us/calculate", json=payload).json == first.json
    assert len(country.calls) == 1
    payload["spm"].update(selection)
    second = client.post("/us/calculate", json=payload)
    assert second.status_code == 200
    assert len(country.calls) == 2
    assert first.json["spm_config"] != second.json["spm_config"]


def test_certification_checked_before_cached_response(certified, harness):
    client, country = harness
    payload = {"household": HOUSEHOLD, "spm": {"geography_kind": "national"}}
    assert client.post("/us/calculate", json=payload).status_code == 200
    certified.clear()
    response = client.post("/us/calculate", json=payload)
    assert response.status_code == 400
    assert response.json["errors"][0]["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
    assert len(country.calls) == 1


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_legacy_country_requests_do_not_receive_spm(harness, country_id):
    client, country = harness
    response = client.post(f"/{country_id}/calculate", json={"household": HOUSEHOLD})
    assert response.status_code == 200
    assert country.calls[0][2] == {}
    assert "spm_provenance" not in response.json
    assert "spm_config" not in response.json


def test_http_cache_default_artifact_hash_is_part_of_identity(certified, harness):
    client, country = harness
    payload = {"household": HOUSEHOLD}
    first = client.post("/us/calculate", json=payload)
    certified["measurements"]["spm"]["forecast_content_sha256"] = "b" * 64
    second = client.post("/us/calculate", json=payload)
    assert first.status_code == second.status_code == 200
    assert len(country.calls) == 2
    assert first.json["spm_config"] != second.json["spm_config"]


def test_linked_household_measurement_is_immutable_for_saved_reports(
    certified, harness, orm_session_factory
):
    client, _ = harness
    created = client.post(
        "/us/household", json={"data": HOUSEHOLD, "spm": {"geography_kind": "national"}}
    )
    household_id = created.json["result"]["household_id"]
    url = f"/us/household/{household_id}"
    simulation = (
        SimulationService(orm_session_factory)
        .get_or_create_simulation("us", str(household_id), "household", 2)
        .simulation
    )
    assert simulation.population_id == str(household_id)

    for payload in [
        {"data": HOUSEHOLD, "spm": {"geography_kind": "county"}},
        {"data": {"people": {"you": {"age": {"2026": 41}}}}},
    ]:
        rejected = client.put(url, json=payload)
        assert rejected.status_code == 405
    assert (
        client.put(url, json={"data": HOUSEHOLD, "label": "New label"}).status_code
        == 405
    )
    saved = client.get(url).json["result"]
    assert saved["spm"]["geography_kind"] == "national"
    assert saved["household_json"] == HOUSEHOLD


def test_certification_protects_linked_households_without_saved_spm(
    certified, harness, orm_session_factory
):
    client, _ = harness
    historical_output = {"result": {"household_net_income": 12345}}
    with orm_session_factory.begin() as session:
        household = Household(
            country_id="us",
            label="Historical household",
            household_json=deepcopy(HOUSEHOLD),
            household_hash="historical-input-hash",
            api_version="historical-model",
        )
        session.add(household)
        session.flush()
        household_id = household.id
        population_id = str(household_id).zfill(5)
        simulation = Simulation(
            country_id="us",
            population_id=population_id,
            population_type="household",
            policy_id=2,
            status="complete",
            output=deepcopy(historical_output),
            api_version="historical-model",
        )
        session.add(simulation)
        session.flush()
        simulation_id = simulation.id

    url = f"/us/household/{household_id}"
    original = client.get(url).json["result"]
    assert "spm" not in original
    changed = {"people": {"you": {"age": {"2026": 41}}}}
    for payload in (
        {"data": changed},
        {"data": HOUSEHOLD, "spm": {"geography_kind": "national"}},
        {"data": HOUSEHOLD, "spm": {}},
    ):
        rejected = client.put(url, json=payload)
        assert rejected.status_code == 405
        assert client.get(url).json["result"] == original

    renamed = client.put(url, json={"data": HOUSEHOLD, "label": "New label"})
    assert renamed.status_code == 405
    assert client.get(url).json["result"] == original

    replacement = client.post(
        "/us/household", json={"data": changed, "spm": {"geography_kind": "national"}}
    )
    assert replacement.status_code == 201
    replacement_id = replacement.json["result"]["household_id"]
    assert replacement_id != household_id
    saved = client.get(f"/us/household/{replacement_id}").json["result"]
    assert saved["household_json"] == changed
    assert saved["spm"]["geography_kind"] == "national"
    replacement_simulation = SimulationService(
        orm_session_factory
    ).get_or_create_simulation("us", str(replacement_id), "household", 2)
    assert replacement_simulation.created is True
    assert replacement_simulation.simulation.id != simulation_id
    assert client.get(url).json["result"] == original
    with orm_session_factory() as session:
        historical = session.get(Simulation, simulation_id)
        assert historical.population_id == population_id
        assert historical.status == "complete"
        assert historical.output == historical_output
        assert historical.api_version == "historical-model"


@pytest.mark.parametrize("write_source", ["cloud_sql", "dual_write"])
def test_household_creation_retains_resolved_spm_before_selected_mirror(
    certified, harness, orm_session_factory, monkeypatch, write_source
):
    from policyengine_api.data.v1_models import HouseholdMirrorEvent
    from sqlalchemy import select
    from unittest.mock import Mock

    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", write_source)
    observed = []

    def copy_committed_event(country_id, household_id, **_kwargs):
        with orm_session_factory() as session:
            household = session.get(Household, household_id)
            event = session.scalar(
                select(HouseholdMirrorEvent).where(
                    HouseholdMirrorEvent.legacy_household_id == household_id
                )
            )
            assert household.country_id == country_id == "us"
            assert event is not None
            snapshot = event.payload_json["snapshot"]
            assert snapshot["household_json"] == household.household_json
            assert snapshot["source_household_hash"] == household.household_hash
            observed.append(deepcopy(snapshot["household_json"]["spm"]))

    copy_event = Mock(side_effect=copy_committed_event)
    monkeypatch.setattr(
        household_routes, "process_household_event_after_commit", copy_event
    )
    client, country = harness
    created = client.post(
        "/us/household", json={"data": HOUSEHOLD, "spm": {"geography_kind": "national"}}
    )
    assert created.status_code == 201
    saved = client.get(f"/us/household/{created.json['result']['household_id']}").json[
        "result"
    ]
    assert saved["spm"]["forecast_content_sha256"] == FORECAST_HASH
    assert saved["spm"]["geography_kind"] == "national"
    assert country.calls == []
    if write_source == "dual_write":
        copy_event.assert_called_once()
        assert observed == [saved["spm"]]
    else:
        copy_event.assert_not_called()
        with orm_session_factory() as session:
            assert session.scalar(select(HouseholdMirrorEvent)) is None


@pytest.mark.parametrize("write_source", ["cloud_sql", "dual_write"])
def test_invalid_spm_stops_before_database_and_mirror(
    certified, harness, monkeypatch, write_source
):
    from unittest.mock import Mock

    sessions = Mock()
    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", write_source)
    monkeypatch.setattr(
        household_routes, "household_service", HouseholdService(sessions)
    )
    copy_event = Mock()
    monkeypatch.setattr(
        household_routes, "process_household_event_after_commit", copy_event
    )
    client, _ = harness
    response = client.post(
        "/us/household", json={"data": HOUSEHOLD, "spm": {"geography_kind": "metro"}}
    )
    assert response.status_code == 400
    assert response.json["errors"][0]["code"] == "SPM_SETTINGS_INVALID"
    sessions.begin.assert_not_called()
    copy_event.assert_not_called()


@pytest.mark.parametrize("write_source", ["cloud_sql", "dual_write"])
def test_valid_spm_database_timeout_keeps_stage11_safe_persistence_response(
    certified, harness, monkeypatch, write_source
):
    from sqlalchemy.exc import TimeoutError
    from unittest.mock import Mock

    sessions = Mock()
    sessions.begin.side_effect = TimeoutError("database credential secret")
    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", write_source)
    monkeypatch.setattr(
        household_routes, "household_service", HouseholdService(sessions)
    )
    copy_event = Mock()
    monkeypatch.setattr(
        household_routes, "process_household_event_after_commit", copy_event
    )
    client, _ = harness
    response = client.post(
        "/us/household", json={"data": HOUSEHOLD, "spm": {"geography_kind": "national"}}
    )
    assert response.status_code == 503
    assert response.json["status"] == "error"
    assert "SPM_SETTINGS_INVALID" not in response.text
    assert "secret" not in response.text
    sessions.begin.assert_called_once()
    copy_event.assert_not_called()


def test_stored_replay_hits_the_trace_cache_when_a_receipt_omits_nulls(
    certified, harness
):
    """A canonical country may omit null receipt settings; replay must still hit.

    Requiring exact JSON equality between the receipt and the resolved identity
    made every stored replay recompute.
    """
    client, country = harness
    calculate = country.calculate

    def omitting_null_settings(household, policy, **kwargs):
        result = calculate(household, policy, **kwargs)
        return CalculationResult(
            result.household,
            result.tracer_output,
            {
                key: value
                for key, value in result.spm_config.items()
                if value is not None
            },
            result.spm_provenance,
        )

    country.calculate = omitting_null_settings
    created = client.post(
        "/us/household", json={"data": HOUSEHOLD, "spm": {"geography_kind": "national"}}
    )
    assert created.status_code == 201, created.json
    url = f"/us/household/{created.json['result']['household_id']}/policy/2"
    first = client.get(url)
    assert first.status_code == 200, first.json
    assert set(first.json["spm_config"]) == {
        "forecast_content_sha256",
        "scenario",
        "geography_kind",
        "county_vintage",
    }
    cached = client.get(url)
    assert cached.status_code == 200
    assert cached.json == first.json
    assert len(country.calls) == 1


@pytest.mark.parametrize("version", ["5.2.1", "5.4.0", "6.0.0"])
def test_bundle_version_bump_without_measurements_still_serves_us_requests(
    harness, monkeypatch, version
):
    """A bundle bump for unrelated reasons must not 400 every US surface.

    The automated bundle update moves these version strings on its own, so an
    allowlist of known versions turns a routine release into a US outage.
    """
    monkeypatch.setattr(
        spm,
        "_current_bundle",
        lambda: {
            "policyengine_version": version,
            "packages": {"policyengine-us": {"version": "1.764.6"}},
        },
    )
    client, country = harness
    for path in ("/us/calculate", "/us/calculate-full"):
        response = client.post(path, json={"household": HOUSEHOLD})
        assert response.status_code == 200, (path, response.json)
        assert "spm_config" not in response.json

    created = client.post("/us/household", json={"data": HOUSEHOLD})
    assert created.status_code == 201, created.json
    household_id = created.json["result"]["household_id"]
    assert "spm" not in client.get(f"/us/household/{household_id}").json["result"]
    replay = client.get(f"/us/household/{household_id}/policy/2")
    assert replay.status_code == 200, replay.json
    assert "spm_config" not in replay.json
    assert all(call[2] == {} for call in country.calls)

    # An explicit selection is still refused rather than silently ignored.
    refused = client.post(
        "/us/calculate",
        json={"household": HOUSEHOLD, "spm": {"geography_kind": "national"}},
    )
    assert refused.status_code == 400
    assert refused.json["errors"][0]["code"] == "SPM_SETTINGS_UNSUPPORTED"


def test_canonical_model_without_certification_refuses_every_us_surface(
    harness, monkeypatch
):
    """Capability without a certified configuration still fails closed."""
    monkeypatch.setattr(
        spm,
        "_current_bundle",
        lambda: {
            "policyengine_version": "5.2.0",
            "packages": {"policyengine-us": {"version": "1.764.6"}},
        },
    )
    monkeypatch.setattr(spm, "simulation_supports_spm", lambda _: True)
    client, country = harness
    for path in ("/us/calculate", "/us/calculate-full", "/us/household"):
        response = client.post(path, json={"household": HOUSEHOLD, "data": HOUSEHOLD})
        assert response.status_code == 400, (path, response.json)
        assert response.json["errors"][0]["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
    assert country.calls == []
