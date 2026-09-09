"""Saved household references preserve their measurement and input identity."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from policyengine_api.data.v1_models import Household, Simulation
from policyengine_api.services import household_service
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.spm import SPMValidationError


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
def canonical_household(monkeypatch, orm_session_factory):
    def normalize(country_id, selection):
        assert country_id == "us"
        return {**NATIONAL, **(selection or {})}

    monkeypatch.setattr(household_service, "normalize_spm_selection", normalize)
    service = HouseholdService(orm_session_factory)
    household = service.create_household(
        "us", INPUTS, "Original", spm=NATIONAL
    ).household
    return service, household


def test_numeric_household_aliases_share_canonical_simulation_identity(
    canonical_household, orm_session_factory
):
    _, household = canonical_household
    simulations = SimulationService(orm_session_factory)

    first = simulations.get_or_create_simulation(
        "us", str(household.id).zfill(5), "household", 1
    )
    second = simulations.get_or_create_simulation(
        "us", str(household.id), "household", 1
    )

    assert first.created is True
    assert second.created is False
    assert first.simulation.id == second.simulation.id
    assert first.simulation.population_id == str(household.id)
    assert first.simulation.simulation_spec_json["population_id"] == str(household.id)


def test_uk_household_population_ids_keep_their_existing_representation(
    orm_session_factory,
):
    created = SimulationService(orm_session_factory).get_or_create_simulation(
        "uk", "0001", "household", 1
    )
    assert created.simulation.population_id == "0001"
    assert created.simulation.simulation_spec_json["population_id"] == "0001"


@pytest.mark.parametrize("unrelated_id", ["1suffix", "1.0", "+1", " 1", "1\n", "١"])
def test_numeric_alias_lookup_does_not_reuse_nonnumeric_population_ids(
    orm_session_factory, unrelated_id
):
    with orm_session_factory.begin() as session:
        session.add(
            Simulation(
                country_id="us",
                population_id=unrelated_id,
                api_version="historical",
                population_type="household",
                policy_id=1,
                status="complete",
                output={"unrelated": True},
            )
        )

    result = SimulationService(orm_session_factory).get_or_create_simulation(
        "us", "0001", "household", 1
    )
    assert result.created is True
    assert result.simulation.population_id == "1"
    assert result.simulation.output is None


def test_exact_historical_identity_wins_over_an_existing_numeric_alias(
    orm_session_factory,
):
    with orm_session_factory.begin() as session:
        historical = Simulation(
            country_id="us",
            population_id="00001",
            api_version="historical",
            population_type="household",
            policy_id=1,
            status="complete",
            output={"historical": True},
        )
        session.add(historical)
        session.flush()
        historical_id = historical.id
        session.add(
            Simulation(
                country_id="us",
                population_id="1",
                api_version="historical",
                population_type="household",
                policy_id=1,
                status="pending",
            )
        )

    result = SimulationService(orm_session_factory).get_or_create_simulation(
        "us", "00001", "household", 1
    )
    assert result.created is False
    assert result.simulation.id == historical_id
    assert result.simulation.status == "complete"
    assert result.simulation.output == {"historical": True}


def test_replacement_household_preserves_historical_zero_padded_reference(
    canonical_household, orm_session_factory
):
    service, household = canonical_household
    original = deepcopy(household.household_json)
    with orm_session_factory.begin() as session:
        session.add(
            Simulation(
                country_id="us",
                population_id=str(household.id).zfill(5),
                population_type="household",
                policy_id=1,
                api_version="historical",
                status="complete",
                output={"spm_config": NATIONAL},
            )
        )

    replacement = service.create_household(
        "us", INPUTS, "Replacement", spm={"geography_kind": "county"}
    ).household

    assert replacement.id != household.id
    assert replacement.household_hash != household.household_hash
    assert replacement.household_json["spm"]["geography_kind"] == "county"
    replay = SimulationService(orm_session_factory).get_or_create_simulation(
        "us", str(household.id), "household", 1
    )
    assert replay.created is False
    assert replay.simulation.population_id == str(household.id).zfill(5)
    assert replay.simulation.output == {"spm_config": NATIONAL}

    saved = service.get_household("us", household.id)
    assert saved.household_json == original
    assert saved.household_hash == household.household_hash


def test_legacy_read_does_not_reinterpret_inputs_when_certificate_unavailable(
    monkeypatch, orm_session_factory
):
    with orm_session_factory.begin() as session:
        household = Household(
            country_id="us",
            label="Original",
            household_json=deepcopy(INPUTS),
            household_hash="original-input-hash",
            api_version="legacy-test",
        )
        session.add(household)
        session.flush()
        household_id = household.id
    SimulationService(orm_session_factory).get_or_create_simulation(
        "us", str(household_id), "household", 1
    )
    normalize = Mock(
        side_effect=SPMValidationError(
            "SPM_CONFIGURATION_UNAVAILABLE", "Future bundle is not certified"
        )
    )
    monkeypatch.setattr(household_service, "normalize_spm_selection", normalize)

    service = HouseholdService(orm_session_factory)
    saved = service.get_household("us", household_id)

    normalize.assert_not_called()
    assert saved.label == "Original"
    assert saved.household_json == INPUTS
    assert saved.household_hash == "original-input-hash"
    assert saved.api_version == "legacy-test"
