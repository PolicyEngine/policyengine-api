from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import (
    ComputedHousehold,
    Household,
    Policy,
    Tracer,
)
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
)


PACKAGE_ROOT = Path(__file__).parents[3] / "policyengine_api"


class TrackingSessionFactory:
    def __init__(self, factory):
        self.factory = factory
        self.active_scopes = 0

    @contextmanager
    def __call__(self):
        self.active_scopes += 1
        try:
            with self.factory() as session:
                yield session
        finally:
            self.active_scopes -= 1

    @contextmanager
    def begin(self):
        self.active_scopes += 1
        try:
            with self.factory.begin() as session:
                yield session
        finally:
            self.active_scopes -= 1


def _seed_inputs(factory):
    with factory.begin() as session:
        session.add_all(
            [
                Household(
                    id=1,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    household_json={"people": {"you": {}}},
                    household_hash="household-hash",
                ),
                Policy(
                    id=2,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    policy_json={},
                    policy_hash="policy-hash",
                ),
            ]
        )


def test_household_endpoint_and_country_do_not_manage_persistence():
    endpoint_source = (PACKAGE_ROOT / "endpoints" / "household.py").read_text(
        encoding="utf-8"
    )
    country_source = (PACKAGE_ROOT / "country.py").read_text(encoding="utf-8")
    assert "get_v1_session_factory" not in endpoint_source
    assert "from sqlalchemy" not in endpoint_source
    assert "select(" not in endpoint_source
    assert "get_v1_session_factory" not in country_source
    assert "Tracer(" not in country_source


def test_calculation_closes_reads_before_compute_and_persists_local_results(
    orm_session_factory,
):
    _seed_inputs(orm_session_factory)
    primary = TrackingSessionFactory(orm_session_factory)
    local = TrackingSessionFactory(orm_session_factory)

    class Country:
        metadata = {
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
        }

        def calculate(self, household, policy):
            assert primary.active_scopes == 0
            assert local.active_scopes == 0
            return SimpleNamespace(
                household={"people": {"you": {"net_income": {"2026": 42}}}},
                tracer_output=["net_income <2026>"],
            )

    service = HouseholdCalculationService(
        primary_session_factory=primary,
        local_session_factory=local,
        country_provider=lambda: {"us": Country()},
    )

    result = service.calculate_stored_household("us", 1, 2)

    assert result.household["people"]["you"]["net_income"]["2026"] == 42
    with orm_session_factory() as session:
        cached = session.scalar(select(ComputedHousehold))
        tracer = session.scalar(select(Tracer))
        assert cached.computed_household_json == result.household
        assert tracer.tracer_output == ["net_income <2026>"]


def test_calculation_uses_local_cache_without_recomputing(orm_session_factory):
    _seed_inputs(orm_session_factory)
    calculated = {"people": {"you": {"net_income": {"2026": 42}}}}
    with orm_session_factory.begin() as session:
        session.add(
            ComputedHousehold(
                household_id=1,
                policy_id=2,
                country_id="us",
                api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                computed_household_json=calculated,
                status="complete",
            )
        )
    country = SimpleNamespace(
        metadata={"variables": {}, "entities": {}},
        calculate=lambda *_: (_ for _ in ()).throw(
            AssertionError("cache hit should not calculate")
        ),
    )
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        local_session_factory=orm_session_factory,
        country_provider=lambda: {"us": country},
    )

    result = service.calculate_stored_household("us", 1, 2)

    assert result.household == calculated
    assert result.cached is True


def test_local_computed_household_and_tracer_write_roll_back_together(
    orm_session_factory,
    monkeypatch,
):
    _seed_inputs(orm_session_factory)
    country = SimpleNamespace(
        metadata={
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
        },
        calculate=lambda *_: SimpleNamespace(
            household={"people": {"you": {}}},
            tracer_output=["trace"],
        ),
    )
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        local_session_factory=orm_session_factory,
        country_provider=lambda: {"us": country},
    )
    session_type = orm_session_factory.class_
    original_flush = session_type.flush

    def fail_tracer_flush(session, *args, **kwargs):
        has_tracer = any(isinstance(value, Tracer) for value in session.new)
        original_flush(session, *args, **kwargs)
        if has_tracer:
            raise RuntimeError("tracer insert failed")

    monkeypatch.setattr(session_type, "flush", fail_tracer_flush)

    with pytest.raises(RuntimeError, match="tracer insert failed"):
        service.calculate_stored_household("us", 1, 2)

    monkeypatch.setattr(session_type, "flush", original_flush)
    with orm_session_factory() as session:
        assert session.scalar(select(ComputedHousehold)) is None
        assert session.scalar(select(Tracer)) is None
