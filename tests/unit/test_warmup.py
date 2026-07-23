import sys
import types
from pathlib import Path

from policyengine_api import warmup

REPO = Path(__file__).resolve().parents[2]


def test_requested_countries_default(monkeypatch):
    monkeypatch.delenv("POLICYENGINE_API_WARMUP_COUNTRIES", raising=False)
    assert warmup._requested_countries() == ["us"]


def test_requested_countries_parses_env(monkeypatch):
    monkeypatch.setenv("POLICYENGINE_API_WARMUP_COUNTRIES", "US, uk ,")
    assert warmup._requested_countries() == ["us", "uk"]


def test_us_warmup_household_requests_a_broad_output():
    household = warmup.WARMUP_HOUSEHOLDS["us"]
    assert household["people"]
    net_income = household["households"]["household"]["household_net_income"]
    # A null value marks it as a requested computation for calculate().
    assert None in net_income.values()


def test_all_warmup_household_members_reference_defined_people():
    # Cheap structural guard (no tax-benefit-system build): a typo'd member would
    # make the real warmup calculate throw, which is swallowed and would silently
    # leave the service unwarmed. The full validity check is the slow integration
    # test in tests/integration/test_warmup_household.py.
    for country_id, household in warmup.WARMUP_HOUSEHOLDS.items():
        people = set(household.get("people", {}))
        assert people, f"{country_id} warmup household defines no people"
        for entity_plural, entities in household.items():
            if entity_plural == "people" or not isinstance(entities, dict):
                continue
            for entity in entities.values():
                for member in entity.get("members", []):
                    assert member in people, (
                        f"{country_id}: {entity_plural} member {member!r} is not a "
                        "defined person"
                    )


def _inject_fake_countries(monkeypatch, countries):
    module = types.ModuleType("policyengine_api.country")
    module.COUNTRIES = countries
    monkeypatch.setitem(sys.modules, "policyengine_api.country", module)


def test_run_startup_warmup_calculates_each_country(monkeypatch):
    calls = []

    class FakeCountry:
        def calculate(self, household, reform):
            calls.append((household, reform))

    _inject_fake_countries(monkeypatch, {"us": FakeCountry()})
    monkeypatch.setenv("POLICYENGINE_API_WARMUP_COUNTRIES", "us")

    warmup.run_startup_warmup()

    assert len(calls) == 1
    household, reform = calls[0]
    assert household["people"]
    assert reform == {}


def test_run_startup_warmup_swallows_calculate_errors(monkeypatch):
    class BoomCountry:
        def calculate(self, household, reform):
            raise RuntimeError("boom")

    _inject_fake_countries(monkeypatch, {"us": BoomCountry()})
    monkeypatch.setenv("POLICYENGINE_API_WARMUP_COUNTRIES", "us")

    # Must not raise: a warmup failure cannot stop the worker from serving.
    warmup.run_startup_warmup()


def test_run_startup_warmup_skips_unknown_country(monkeypatch):
    calls = []

    class FakeCountry:
        def calculate(self, household, reform):
            calls.append(1)

    _inject_fake_countries(monkeypatch, {"us": FakeCountry()})
    monkeypatch.setenv("POLICYENGINE_API_WARMUP_COUNTRIES", "zz")

    warmup.run_startup_warmup()
    assert calls == []


def test_asgi_runs_warmup_and_marks_ready():
    src = (REPO / "policyengine_api/asgi.py").read_text(encoding="utf-8")
    assert "run_startup_warmup" in src
    assert "mark_ready" in src


def test_readiness_check_gates_on_readiness():
    src = (REPO / "policyengine_api/api.py").read_text(encoding="utf-8")
    assert "is_ready" in src
    assert "status=503" in src
