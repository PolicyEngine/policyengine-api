"""Submit a stored household's calculation only after the Public API's own checks."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.services.v2.household_calculations.services import (
    V2HouseholdCalculationService,
)
from policyengine_api.services.v2.household_calculations.types import (
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
    HouseholdCalculationStorageError,
    HouseholdCalculationYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
    PolicyParametersMissingError,
)
from tests.fixtures.household_calculation_documents import JOB_ID
from tests.unit.v2.household_calculation_support import (
    HOUSEHOLD_ID,
    POLICY_ID,
    REFORMED_PARAMETER,
    FakeCountries,
    FakeHouseholds,
    FakePolicies,
    FakeSimulation,
    calculation_input,
    household_read,
    policy_read,
)


class UnreadableDatabase:
    """A household job database whose every read fails."""

    @contextmanager
    def read(self):
        msg = "SELECT household_jobs"
        raise OperationalError(msg, {}, Exception("connection refused"))
        yield


class Services:
    """The service under test and the stand-ins it reads and calls."""

    def __init__(self) -> None:
        self.countries = FakeCountries()
        self.households = FakeHouseholds()
        self.policies = FakePolicies()
        self.simulation = FakeSimulation()
        self.simulation_requests = 0

    def simulation_factory(self) -> FakeSimulation:
        self.simulation_requests += 1
        return self.simulation

    def service(self, database=None) -> V2HouseholdCalculationService:
        return V2HouseholdCalculationService(
            countries=self.countries,
            households=self.households,
            policies=self.policies,
            database_session=database or UnreadableDatabase(),
            simulation_factory=self.simulation_factory,
        )


@pytest.fixture
def services() -> Services:
    return Services()


def test_a_calculation_is_sent_as_given_and_returned_with_its_year(services) -> None:
    calculation = calculation_input(add_missing_variables=True)

    submitted = services.service().submit_calculation(calculation)

    assert services.simulation.submissions == [calculation]
    assert services.households.reads == [("us", HOUSEHOLD_ID)]
    assert services.policies.reads == [("us", POLICY_ID)]
    assert submitted.calculation_id == JOB_ID
    assert submitted.status == "pending"
    assert (submitted.country_id, submitted.household_id) == ("us", HOUSEHOLD_ID)
    assert submitted.policy_id == POLICY_ID
    assert submitted.year == 2026


def test_current_law_reads_no_policy(services) -> None:
    submitted = services.service().submit_calculation(calculation_input(policy_id=None))

    assert services.policies.reads == []
    assert submitted.policy_id is None
    (sent,) = services.simulation.submissions
    assert sent.policy_id is None


def test_a_household_only_country_is_calculated(services) -> None:
    services.households.households[("uk", HOUSEHOLD_ID)] = household_read()

    services.service().submit_calculation(
        calculation_input(country_id="uk", policy_id=None)
    )

    assert services.households.reads == [("uk", HOUSEHOLD_ID)]
    assert len(services.simulation.submissions) == 1


def test_a_country_without_household_calculations_is_refused_first(services) -> None:
    services.countries.rows = services.countries.rows[1:]

    with pytest.raises(HouseholdCalculationCountryError, match="uk"):
        services.service().submit_calculation(calculation_input(country_id="uk"))

    assert services.households.reads == []
    assert services.simulation_requests == 0


def test_an_unknown_household_is_not_found_before_its_policy_is_read(
    services,
) -> None:
    with pytest.raises(HouseholdNotFoundError):
        services.service().submit_calculation(calculation_input(household_id=uuid4()))

    assert services.policies.reads == []
    assert services.simulation_requests == 0


def test_an_unknown_policy_is_not_found_before_the_year_is_checked(services) -> None:
    services.households.households[("us", HOUSEHOLD_ID)] = household_read(
        default_year=None
    )

    with pytest.raises(PolicyNotFoundError):
        services.service().submit_calculation(calculation_input(policy_id=uuid4()))

    assert services.simulation_requests == 0


def test_a_policy_of_another_country_is_not_found(services) -> None:
    services.households.households[("uk", HOUSEHOLD_ID)] = household_read()

    with pytest.raises(PolicyNotFoundError):
        services.service().submit_calculation(calculation_input(country_id="uk"))

    assert services.policies.reads == [("uk", POLICY_ID)]
    assert services.simulation_requests == 0


def test_a_household_without_a_default_year_is_refused(services) -> None:
    services.households.households[("us", HOUSEHOLD_ID)] = household_read(
        default_year=None
    )

    with pytest.raises(HouseholdCalculationYearError):
        services.service().submit_calculation(calculation_input())

    assert services.simulation_requests == 0


def test_a_policy_setting_parameters_the_catalog_lacks_is_refused(services) -> None:
    services.policies.policies[("us", POLICY_ID)] = policy_read(
        missing_parameters=(REFORMED_PARAMETER,)
    )

    with pytest.raises(PolicyParametersMissingError) as refused:
        services.service().submit_calculation(calculation_input())

    assert refused.value.missing_parameters == (REFORMED_PARAMETER,)
    assert services.simulation_requests == 0


def test_a_policy_no_published_catalog_could_check_is_sent(services) -> None:
    services.policies.policies[("us", POLICY_ID)] = policy_read(missing_parameters=None)

    services.service().submit_calculation(calculation_input())

    assert len(services.simulation.submissions) == 1


@pytest.mark.parametrize(
    "refusal",
    [
        SimulationServiceInvalidRequestError("the contract refuses the household"),
        SimulationServiceUnavailableError("The simulation service answered 503."),
    ],
)
def test_the_simulation_services_refusals_reach_the_caller(services, refusal) -> None:
    services.simulation.error = refusal

    with pytest.raises(type(refusal), match=str(refusal)):
        services.service().submit_calculation(calculation_input())


def test_an_unreadable_database_while_checking_is_a_storage_error(services) -> None:
    services.countries.error = OperationalError(
        "SELECT countries", {}, Exception("connection refused")
    )

    with pytest.raises(HouseholdCalculationStorageError):
        services.service().submit_calculation(calculation_input())

    assert services.simulation_requests == 0


def test_an_unreadable_database_while_reading_is_a_storage_error(services) -> None:
    with pytest.raises(HouseholdCalculationStorageError):
        services.service(UnreadableDatabase()).get_calculation(JOB_ID)

    assert services.simulation_requests == 0
