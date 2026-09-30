from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.v1_models import (
    Household,
    Policy,
)
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_calculations import (
    CachedHouseholdCalculation,
    HouseholdCalculationCache,
    HouseholdCalculationIdentity,
)
from policyengine_api.services.household_calculation_service import (
    CalculationResult,
    HouseholdCalculationService,
    HouseholdNotFoundError,
    PolicyNotFoundError,
)
from tests.fixtures.spm import INSTALLED_SPM_SELECTION, household_result_fields


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


def _cache() -> HouseholdCalculationCache:
    return HouseholdCalculationCache(
        InMemoryCacheBackend(),
        CacheNamespace("test", "api"),
    )


def _identity() -> HouseholdCalculationIdentity:
    return HouseholdCalculationIdentity(
        country_id="us",
        household_id=1,
        policy_id=2,
        household_hash="household-hash",
        policy_hash="policy-hash",
        country_package_version=COUNTRY_PACKAGE_VERSIONS["us"],
        policyengine_version=POLICYENGINE_VERSION,
        spm=INSTALLED_SPM_SELECTION,
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


def test_calculate_household_preserves_calculation_warnings():
    household = {"people": {"you": {"employment_income": {"2026": None}}}}

    class Country:
        metadata = {
            "variables": {"employment_income": {"entity": "person"}},
            "entities": {"person": {"plural": "people", "roles": {}}},
            "parameters": {},
        }

        def calculate(self, household, policy, **_kwargs):
            return CalculationResult(
                household=household,
                warnings=("employment_income could not be calculated",),
            )

    service = HouseholdCalculationService(
        cache=_cache(),
        country_provider=lambda: {"us": Country()},
    )

    result = service.calculate_household("us", household, {})

    assert result.warnings == ("employment_income could not be calculated",)


def test_parsed_country_calculation_is_reused_for_calculation():
    parsed_calculation = object()

    class Country:
        metadata = {
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
            "parameters": {},
        }

        def __init__(self):
            self.prepare = Mock(return_value=parsed_calculation)
            self.calculate = Mock(
                return_value=CalculationResult(household={"people": {}})
            )

        def prepare_calculation(self, household, policy, **kwargs):
            return self.prepare(household, policy, **kwargs)

    country = Country()
    service = HouseholdCalculationService(
        cache=_cache(),
        country_provider=lambda: {"us": country},
    )
    prepared = service.prepare_household_calculation(
        "us",
        {"people": {}},
        {},
    )

    parsed = service.parse_prepared_household(prepared)
    result = service.calculate_prepared_household(parsed)

    country.prepare.assert_called_once_with(
        {"people": {}},
        {},
        spm=prepared.spm,
        spm_requested=prepared.spm_requested,
    )
    country.calculate.assert_called_once_with(
        {"people": {}},
        {},
        spm=prepared.spm,
        spm_requested=prepared.spm_requested,
        prepared=parsed_calculation,
    )
    assert result.household == {"people": {}}


def test_successful_situation_parsing_accepts_calculation_before_stage_ends():
    accepted = Mock()

    class Country:
        metadata = {
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
            "parameters": {},
        }

        def prepare_calculation(self, household, policy, **_kwargs):
            return object()

    service = HouseholdCalculationService(
        cache=_cache(),
        country_provider=lambda: {"us": Country()},
    )
    prepared = service.prepare_household_calculation("us", {"people": {}}, {})

    parsed = service.parse_prepared_household(
        prepared,
        on_accepted=accepted,
    )

    assert parsed.country_calculation is not None
    accepted.assert_called_once_with()


def test_failed_situation_parsing_does_not_accept_calculation():
    accepted = Mock()

    class Country:
        metadata = {
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
            "parameters": {},
        }

        def prepare_calculation(self, household, policy, **_kwargs):
            raise RuntimeError("invalid situation")

    service = HouseholdCalculationService(
        cache=_cache(),
        country_provider=lambda: {"us": Country()},
    )
    prepared = service.prepare_household_calculation("us", {"people": {}}, {})

    with pytest.raises(RuntimeError, match="invalid situation"):
        service.parse_prepared_household(
            prepared,
            on_accepted=accepted,
        )

    accepted.assert_not_called()


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

        def calculate(self, household, policy, **_kwargs):
            assert primary.active_scopes == 0
            return CalculationResult(
                household={"people": {"you": {"net_income": {"2026": 42}}}},
                warnings=("net_income could not be calculated",),
                **household_result_fields(years=["2026"]),
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
    assert cached.warnings == result.warnings == ("net_income could not be calculated",)
    assert "recompute" in {
        call.args[0]["cache_event"] for call in mock_logger.log_struct.call_args_list
    }


def test_missing_stored_household_is_not_accepted(orm_session_factory):
    accepted = Mock()
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=_cache(),
    )

    with pytest.raises(HouseholdNotFoundError):
        service.calculate_stored_household(
            "us",
            1,
            2,
            on_accepted=accepted,
        )

    accepted.assert_not_called()


def test_missing_stored_policy_is_not_accepted(orm_session_factory):
    with orm_session_factory.begin() as session:
        session.add(
            Household(
                id=1,
                country_id="us",
                label=None,
                api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                household_json={"people": {"you": {}}},
                household_hash="household-hash",
            )
        )
    accepted = Mock()
    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=_cache(),
    )

    with pytest.raises(PolicyNotFoundError):
        service.calculate_stored_household(
            "us",
            1,
            2,
            on_accepted=accepted,
        )

    accepted.assert_not_called()


def test_calculation_uses_local_cache_without_recomputing(orm_session_factory):
    _seed_inputs(orm_session_factory)
    calculated = {"people": {"you": {"net_income": {"2026": 42}}}}
    cache = _cache()
    cache.set(
        _identity(),
        CachedHouseholdCalculation(
            household=calculated,
            warnings=("net_income could not be calculated",),
            **household_result_fields(years=["2026"]),
        ),
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
    accepted = Mock()

    result = service.calculate_stored_household(
        "us",
        1,
        2,
        on_accepted=accepted,
    )

    assert result.household == calculated
    assert result.warnings == ("net_income could not be calculated",)
    assert result.cached is True
    accepted.assert_called_once_with()


def test_failed_cache_write_does_not_invalidate_successful_calculation(
    orm_session_factory,
):
    _seed_inputs(orm_session_factory)
    country = SimpleNamespace(
        metadata={
            "variables": {},
            "entities": {"person": {"plural": "people", "roles": {}}},
        },
        calculate=lambda *_, **__: SimpleNamespace(
            household={"people": {"you": {}}},
            **household_result_fields(years=["2026"]),
        ),
    )

    class BrokenBackend(InMemoryCacheBackend):
        def set(self, *_args, **_kwargs):
            raise OSError("cache unavailable")

    service = HouseholdCalculationService(
        primary_session_factory=orm_session_factory,
        cache=HouseholdCalculationCache(
            BrokenBackend(),
            CacheNamespace("test", "api"),
        ),
        country_provider=lambda: {"us": country},
    )

    result = service.calculate_stored_household("us", 1, 2)
    assert result.household == {"people": {"you": {}}}
    assert result.cached is False
