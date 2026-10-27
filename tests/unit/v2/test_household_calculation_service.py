"""Sending a stored household's calculation to the simulation service; reading it."""

from __future__ import annotations

from uuid import uuid4

import pytest

from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.household_calculations.services import (
    V2HouseholdCalculationService,
)
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationInput,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
    HouseholdCalculationNotFoundError,
    HouseholdCalculationYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from tests.unit.v2.household_calculation_support import (
    CALCULATION_ID,
    CATALOG_VERSION_ID,
    HOUSEHOLD_ID,
    POLICY_ID,
    POLICYENGINE_VERSION,
    SITUATION,
    SPM_CHOICE,
    SPM_CONFIG,
    SPM_PROVENANCE,
    FakeCatalogs,
    FakeCountries,
    FakeHouseholds,
    FakePolicies,
    FakeSimulation,
    household_read,
    simulation_calculation,
    succeeded_calculation,
)

AXES = [[{"name": "employment_income", "count": 5, "min": 0, "max": 80000}]]


class Parts:
    """The service's collaborators, kept for the assertions."""

    def __init__(self, countries: FakeCountries | None = None) -> None:
        """Build every fake."""
        self.countries = countries or FakeCountries()
        self.households = FakeHouseholds()
        self.policies = FakePolicies()
        self.catalogs = FakeCatalogs()
        self.simulation = FakeSimulation()
        self.service = V2HouseholdCalculationService(
            countries=self.countries,
            households=self.households,
            policies=self.policies,
            catalogs=self.catalogs,
            simulation=self.simulation,
        )


def calculation_input(**changes: object) -> HouseholdCalculationInput:
    """Return a calculation of the stored US household under the stored reform."""
    values: dict[str, object] = {
        "country_id": "us",
        "household_id": HOUSEHOLD_ID,
        "policy_id": POLICY_ID,
    }
    values.update(changes)
    return HouseholdCalculationInput.model_validate(values)


def test_a_calculation_sends_the_stored_household_policy_and_catalog() -> None:
    parts = Parts()

    calculation = parts.service.submit_calculation(
        calculation_input(axes=AXES, add_missing_variables=True)
    )

    (submission,) = parts.simulation.submissions
    assert submission == {
        "country": "us",
        "catalog_version_id": str(CATALOG_VERSION_ID),
        "policyengine_version": POLICYENGINE_VERSION,
        "year": 2026,
        "household_id": str(HOUSEHOLD_ID),
        "household": SITUATION,
        "spm": SPM_CHOICE,
        "policy": {
            "policy_id": str(POLICY_ID),
            "parameters": {
                "gov.irs.credits.ctc.amount.base[0].amount": {
                    "2026-01-01.2100-12-31": 3000
                }
            },
        },
        "options": {"axes": AXES, "add_missing_variables": True},
        "force": False,
        "trigger": "initial",
    }
    assert calculation.calculation_id == CALCULATION_ID
    assert calculation.status == "running"
    assert calculation.result is None
    assert parts.catalogs.closed


def test_current_law_and_no_saved_choice_send_neither() -> None:
    parts = Parts()
    stored = household_read()
    data = {key: value for key, value in stored.household_data.items() if key != "spm"}
    parts.households.households[("us", HOUSEHOLD_ID)] = stored.__class__(
        **{**stored.__dict__, "household_data": data}
    )

    parts.service.submit_calculation(calculation_input(policy_id=None))

    (submission,) = parts.simulation.submissions
    assert "spm" not in submission
    assert submission["policy"] == {"policy_id": None, "parameters": {}}
    assert submission["options"] == {"axes": None, "add_missing_variables": False}


def test_the_year_is_the_households_default_year() -> None:
    parts = Parts()
    parts.households.households[("us", HOUSEHOLD_ID)] = household_read(
        default_year=2027
    )

    parts.service.submit_calculation(calculation_input())

    assert parts.simulation.submissions[0]["year"] == 2027


def test_a_household_without_a_default_year_is_refused() -> None:
    parts = Parts()
    parts.households.households[("us", HOUSEHOLD_ID)] = household_read(
        default_year=None
    )

    with pytest.raises(HouseholdCalculationYearError):
        parts.service.submit_calculation(calculation_input())
    assert parts.simulation.submissions == []


def test_a_country_without_household_calculations_is_refused_by_name() -> None:
    parts = Parts(
        FakeCountries(
            rows=(
                CountryRead(
                    id="us", household_enabled=False, society_wide_enabled=False
                ),
            )
        )
    )

    with pytest.raises(HouseholdCalculationCountryError, match="us"):
        parts.service.submit_calculation(calculation_input())

    assert parts.households.calls == []
    assert parts.simulation.submissions == []


def test_a_household_only_country_is_accepted() -> None:
    parts = Parts()
    uk_household = household_read()
    parts.households.households[("uk", HOUSEHOLD_ID)] = uk_household.__class__(
        **{
            **uk_household.__dict__,
            "country_id": "uk",
            "household_data": {
                "people": [
                    {
                        "id": "person-1",
                        "values": {"age": {"2026": 30}},
                        "memberships": {
                            "household": "household-1",
                            "benunit": "benunit-1",
                        },
                    }
                ],
                "household": [{"id": "household-1", "values": {}}],
                "benunit": [{"id": "benunit-1", "values": {}}],
            },
        }
    )

    parts.service.submit_calculation(calculation_input(country_id="uk", policy_id=None))

    (submission,) = parts.simulation.submissions
    assert submission["country"] == "uk"
    assert set(submission["household"]) == {"people", "households", "benunits"}


def test_an_unknown_household_or_policy_sends_nothing() -> None:
    parts = Parts()

    with pytest.raises(HouseholdNotFoundError):
        parts.service.submit_calculation(calculation_input(household_id=uuid4()))
    with pytest.raises(PolicyNotFoundError):
        parts.service.submit_calculation(calculation_input(policy_id=uuid4()))

    assert parts.simulation.submissions == []


def test_a_us_result_includes_the_spm_choice_applied_and_its_receipt() -> None:
    parts = Parts()
    parts.simulation.read_answers[CALCULATION_ID] = succeeded_calculation()

    calculation = parts.service.get_calculation(CALCULATION_ID)

    assert calculation.status == "succeeded"
    assert calculation.result is not None
    assert calculation.result.spm_config == SPM_CONFIG
    assert calculation.result.spm_provenance == SPM_PROVENANCE
    assert calculation.result.policyengine_version == POLICYENGINE_VERSION
    assert calculation.result.household["households"]["household-1"][
        "household_net_income"
    ] == {"2026": 27000.5}


def test_a_failed_calculation_reads_back_its_error() -> None:
    parts = Parts()
    detail = {"code": "invalid_inputs", "message": "Unrecognized inputs: incme"}
    parts.simulation.read_answers[CALCULATION_ID] = simulation_calculation(
        status="failed",
        error={
            "code": "household_calculation_failed",
            "message": "The household calculation failed: invalid_inputs.",
            "detail": detail,
        },
    )

    calculation = parts.service.get_calculation(CALCULATION_ID)

    assert calculation.status == "failed"
    assert calculation.error is not None
    assert calculation.error.code == "household_calculation_failed"
    assert calculation.error.detail == detail


def test_an_unknown_calculation_is_not_found() -> None:
    with pytest.raises(HouseholdCalculationNotFoundError):
        Parts().service.get_calculation(uuid4())


def test_an_unreachable_simulation_service_is_reported() -> None:
    parts = Parts()
    parts.simulation.error = SimulationServiceUnavailableError("unreachable")

    with pytest.raises(SimulationServiceUnavailableError):
        parts.service.submit_calculation(calculation_input())
