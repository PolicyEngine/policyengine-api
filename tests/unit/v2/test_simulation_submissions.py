"""Check simulations and reports before the simulation service creates them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from policyengine_api.services.v2.simulation_service.services import (
    SimulationSubmissionService,
)
from policyengine_api.services.v2.simulation_service.types import (
    EconomyReportCreationInput,
    EconomySimulationCreationInput,
    SubmittedReport,
    SubmittedSimulation,
)
from policyengine_api.services.v2.simulation_service.validators import (
    EconomyCalculationsUnsupportedError,
)

STORED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c001")
OTHER_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c002")
SERVED_COUNTRIES = [
    CountryRead(id="uk", household_enabled=True, society_wide_enabled=True),
    CountryRead(id="us", household_enabled=True, society_wide_enabled=True),
]
# The UK as a household-only country, with no economy calculations.
HOUSEHOLD_ONLY_UK = [
    CountryRead(id="uk", household_enabled=True, society_wide_enabled=False),
    CountryRead(id="us", household_enabled=True, society_wide_enabled=True),
]


@dataclass
class StoredCountries:
    countries: list[CountryRead] = field(default_factory=lambda: SERVED_COUNTRIES)

    def list_countries(self) -> list[CountryRead]:
        return self.countries


@dataclass
class StoredPolicies:
    """The stored policies: only STORED_POLICY_ID, in the US and the UK."""

    asked: list[tuple[str, UUID]] = field(default_factory=list)

    def get_policy(self, *, country_id: str, policy_id: UUID) -> Any:
        self.asked.append((country_id, policy_id))
        if policy_id != STORED_POLICY_ID:
            msg = f"Policy {policy_id} was not found"
            raise PolicyNotFoundError(msg)
        return object()


@dataclass
class RecordingSimulationService:
    """The simulation service's client, recording what it is sent."""

    reports: list[EconomyReportCreationInput] = field(default_factory=list)
    simulations: list[EconomySimulationCreationInput] = field(default_factory=list)

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        self.reports.append(report)
        return SubmittedReport(report_id=uuid4(), report_run_id=uuid4())

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        self.simulations.append(simulation)
        return SubmittedSimulation(simulation_id=uuid4(), simulation_run_id=uuid4())


def unconfigured_client() -> RecordingSimulationService:
    msg = "the simulation service must not be asked"
    raise AssertionError(msg)


def report_input(**changes: Any) -> EconomyReportCreationInput:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "economy",
        "label": "Reform",
        "year": 2026,
        "region_code": "us",
        "baseline": {},
        "reform": {"policy_id": str(STORED_POLICY_ID)},
    }
    return EconomyReportCreationInput.model_validate({**values, **changes})


def simulation_input(**changes: Any) -> EconomySimulationCreationInput:
    values: dict[str, Any] = {
        "country_id": "uk",
        "kind": "economy",
        "year": 2026,
        "region_code": "uk",
        "policy_id": str(STORED_POLICY_ID),
    }
    return EconomySimulationCreationInput.model_validate({**values, **changes})


def submissions(
    client_factory: Any, policies: StoredPolicies | None = None
) -> SimulationSubmissionService:
    return SimulationSubmissionService(
        countries=StoredCountries(),
        policies=policies or StoredPolicies(),
        client_factory=client_factory,
    )


def test_a_report_is_sent_once_its_country_and_policies_are_checked() -> None:
    client = RecordingSimulationService()
    policies = StoredPolicies()
    report = report_input(
        baseline={"policy_id": str(STORED_POLICY_ID)},
        reform={"policy_id": str(STORED_POLICY_ID)},
    )

    submitted = submissions(lambda: client, policies).submit_report(report)

    assert client.reports == [report]
    assert isinstance(submitted, SubmittedReport)
    assert policies.asked == [("us", STORED_POLICY_ID)]


def test_current_law_needs_no_stored_policy() -> None:
    client = RecordingSimulationService()
    policies = StoredPolicies()

    submissions(lambda: client, policies).submit_report(
        report_input(reform={"dynamic_id": str(uuid4())})
    )

    assert policies.asked == []
    assert len(client.reports) == 1


def test_a_household_only_country_is_refused_before_sending() -> None:
    service = SimulationSubmissionService(
        countries=StoredCountries(countries=HOUSEHOLD_ONLY_UK),
        policies=StoredPolicies(),
        client_factory=unconfigured_client,
    )

    with pytest.raises(EconomyCalculationsUnsupportedError, match="'uk'"):
        service.submit_report(report_input(country_id="uk"))
    with pytest.raises(EconomyCalculationsUnsupportedError, match="'uk'"):
        service.submit_simulation(simulation_input(country_id="uk"))


def test_a_country_without_a_countries_row_is_refused() -> None:
    service = SimulationSubmissionService(
        countries=StoredCountries(countries=SERVED_COUNTRIES[:1]),
        policies=StoredPolicies(),
        client_factory=unconfigured_client,
    )

    with pytest.raises(EconomyCalculationsUnsupportedError, match="'us'"):
        service.submit_report(report_input())


@pytest.mark.parametrize("side", ["baseline", "reform"])
def test_a_report_naming_a_policy_not_stored_in_the_country_is_refused(
    side: str,
) -> None:
    service = submissions(unconfigured_client)

    with pytest.raises(PolicyNotFoundError, match=str(OTHER_POLICY_ID)):
        service.submit_report(
            report_input(**{side: {"policy_id": str(OTHER_POLICY_ID)}})
        )


def test_a_simulation_is_sent_once_its_country_and_policy_are_checked() -> None:
    client = RecordingSimulationService()
    policies = StoredPolicies()
    simulation = simulation_input()

    submitted = submissions(lambda: client, policies).submit_simulation(simulation)

    assert client.simulations == [simulation]
    assert isinstance(submitted, SubmittedSimulation)
    assert policies.asked == [("uk", STORED_POLICY_ID)]


def test_a_simulation_naming_a_policy_not_stored_is_refused() -> None:
    service = submissions(unconfigured_client)

    with pytest.raises(PolicyNotFoundError):
        service.submit_simulation(simulation_input(policy_id=str(OTHER_POLICY_ID)))
