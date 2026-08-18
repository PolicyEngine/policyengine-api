from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.v1_models import (
    Household,
    Policy,
)
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.repositories import (
    HouseholdTraceCache,
    HouseholdTraceIdentity,
    HouseholdTraceValue,
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


def _cache() -> HouseholdTraceCache:
    return HouseholdTraceCache(
        InMemoryCacheBackend(),
        CacheNamespace("test", "api"),
    )


def _identity() -> HouseholdTraceIdentity:
    return HouseholdTraceIdentity(
        country_id="us",
        household_id=1,
        policy_id=2,
        household_hash="household-hash",
        policy_hash="policy-hash",
        country_package_version=COUNTRY_PACKAGE_VERSIONS["us"],
        policyengine_version=POLICYENGINE_VERSION,
    )


def test_household_route_and_country_do_not_manage_persistence():
    route_source = (PACKAGE_ROOT / "routes" / "household_routes.py").read_text(
        encoding="utf-8"
    )
    country_source = (PACKAGE_ROOT / "country.py").read_text(encoding="utf-8")
    assert "get_v1_session_factory" not in route_source
    assert "from sqlalchemy" not in route_source
    assert "select(" not in route_source
    assert "get_v1_session_factory" not in country_source
    assert "Tracer(" not in country_source


def test_calculation_closes_reads_before_compute_and_caches_atomic_results(
    orm_session_factory,
    monkeypatch,
):
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)
    _seed_inputs(orm_session_factory)
    primary = TrackingSessionFactory(orm_session_factory)
    cache = _cache()

    class Country:
        metadata = {
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
        }

        def calculate(self, household, policy):
            assert primary.active_scopes == 0
            return SimpleNamespace(
                household={"people": {"you": {"net_income": {"2026": 42}}}},
                tracer_output=["net_income <2026>"],
            )

    service = HouseholdCalculationService(
        primary_session_factory=primary,
        cache=cache,
        country_provider=lambda: {"us": Country()},
    )

    result = service.calculate_stored_household("us", 1, 2)

    assert result.household["people"]["you"]["net_income"]["2026"] == 42
    cached = cache.get(_identity())
    assert cached is not None
    assert cached.household == result.household
    assert cached.tracer_output == ["net_income <2026>"]
    assert "recompute" in {
        call.args[0]["cache_event"] for call in mock_logger.log_struct.call_args_list
    }


def test_calculation_uses_local_cache_without_recomputing(orm_session_factory):
    _seed_inputs(orm_session_factory)
    calculated = {"people": {"you": {"net_income": {"2026": 42}}}}
    cache = _cache()
    cache.set(
        _identity(),
        HouseholdTraceValue(household=calculated, tracer_output=[]),
    )
    country = SimpleNamespace(
        metadata={"variables": {}, "entities": {}},
        calculate=lambda *_: (_ for _ in ()).throw(
            AssertionError("cache hit should not calculate")
        ),
    )
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=cache,
        country_provider=lambda: {"us": country},
    )

    result = service.calculate_stored_household("us", 1, 2)

    assert result.household == calculated
    assert result.cached is True


def test_failed_cache_write_does_not_invalidate_successful_calculation(
    orm_session_factory,
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

    class BrokenBackend(InMemoryCacheBackend):
        def set(self, *_args, **_kwargs):
            raise OSError("cache unavailable")

    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=HouseholdTraceCache(
            BrokenBackend(),
            CacheNamespace("test", "api"),
        ),
        country_provider=lambda: {"us": country},
    )

    result = service.calculate_stored_household("us", 1, 2)
    assert result.household == {"people": {"you": {}}}
    assert result.cached is False
