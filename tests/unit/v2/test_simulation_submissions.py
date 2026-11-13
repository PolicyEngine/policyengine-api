"""Check simulations and reports before the simulation service creates them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.policies.types import CheckedPolicyRead
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
    PolicyParametersMissingError,
)
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
    SubmissionStorageError,
)

STORED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c001")
OTHER_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c002")
# Stored policies that set parameters the running catalog version lacks.
OUTDATED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c003")
SECOND_OUTDATED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c004")
# A stored policy the running catalog could not check, because the running
# PolicyEngine.py version has no published catalog for the country.
UNCHECKED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c005")
REMOVED_PARAMETERS = ("gov.example.removed_amount", "gov.example.removed_rate")
SECOND_REMOVED_PARAMETERS = ("gov.example.removed_threshold",)
# Each stored policy's parameters the running catalog version lacks, as the
# policy service checks them: empty when all exist, None when not checked.
MISSING_PARAMETERS: dict[UUID, tuple[str, ...] | None] = {
    STORED_POLICY_ID: (),
    OUTDATED_POLICY_ID: REMOVED_PARAMETERS,
    SECOND_OUTDATED_POLICY_ID: SECOND_REMOVED_PARAMETERS,
    UNCHECKED_POLICY_ID: None,
}
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


STORED_AT = datetime(2026, 11, 12, tzinfo=UTC)


def checked_policy(
    policy_id: UUID, country_id: str, missing_parameters: tuple[str, ...] | None
) -> CheckedPolicyRead:
    """Return a stored policy as the policy service checks it."""
    return CheckedPolicyRead(
        id=policy_id,
        country_id=country_id,
        tax_benefit_model_id=uuid4(),
        tax_benefit_model_version_id=uuid4(),
        created_at=STORED_AT,
        updated_at=STORED_AT,
        parameter_values=(),
        missing_parameters=missing_parameters,
    )


@dataclass
class StoredPolicies:
    """The policies in MISSING_PARAMETERS, stored in the US and the UK.

    With ``error``, every read raises it, as a database or catalog that
    cannot be read does.
    """

    error: Exception | None = None
    asked: list[tuple[str, UUID]] = field(default_factory=list)

    def get_policy(self, *, country_id: str, policy_id: UUID) -> CheckedPolicyRead:
        self.asked.append((country_id, policy_id))
        if self.error is not None:
            raise self.error
        if policy_id not in MISSING_PARAMETERS:
            msg = f"Policy {policy_id} was not found"
            raise PolicyNotFoundError(msg)
        return checked_policy(policy_id, country_id, MISSING_PARAMETERS[policy_id])


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


class UnreadHouseholds:
    """The stored households, which an economy submission never reads."""

    def get_household(self, *, country_id: str, household_id: UUID) -> object:
        msg = "an economy submission must not read a household"
        raise AssertionError(msg)


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
        households=UnreadHouseholds(),
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
        households=UnreadHouseholds(),
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
        households=UnreadHouseholds(),
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


@pytest.mark.parametrize("side", ["baseline", "reform"])
def test_a_report_whose_policy_sets_parameters_the_running_catalog_lacks_is_refused(
    side: str,
) -> None:
    service = submissions(unconfigured_client)

    with pytest.raises(PolicyParametersMissingError) as refusal:
        service.submit_report(
            report_input(**{side: {"policy_id": str(OUTDATED_POLICY_ID)}})
        )

    assert refusal.value.policy_id == OUTDATED_POLICY_ID
    assert refusal.value.missing_parameters == REMOVED_PARAMETERS


def test_a_simulation_whose_policy_sets_missing_parameters_is_refused() -> None:
    service = submissions(unconfigured_client)

    with pytest.raises(PolicyParametersMissingError) as refusal:
        service.submit_simulation(simulation_input(policy_id=str(OUTDATED_POLICY_ID)))

    assert refusal.value.policy_id == OUTDATED_POLICY_ID
    assert refusal.value.missing_parameters == REMOVED_PARAMETERS


def test_a_report_with_two_outdated_policies_is_refused_for_its_baseline() -> None:
    service = submissions(unconfigured_client)

    with pytest.raises(PolicyParametersMissingError) as refusal:
        service.submit_report(
            report_input(
                baseline={"policy_id": str(OUTDATED_POLICY_ID)},
                reform={"policy_id": str(SECOND_OUTDATED_POLICY_ID)},
            )
        )

    assert refusal.value.policy_id == OUTDATED_POLICY_ID


@pytest.mark.parametrize("outdated_side", ["baseline", "reform"])
def test_a_policy_not_stored_is_refused_before_another_is_checked_for_parameters(
    outdated_side: str,
) -> None:
    # A policy that is not stored answers 404 whichever side names it, before
    # the other side's missing parameters answer 422.
    other_side = "reform" if outdated_side == "baseline" else "baseline"
    service = submissions(unconfigured_client)

    with pytest.raises(PolicyNotFoundError, match=str(OTHER_POLICY_ID)):
        service.submit_report(
            report_input(
                **{
                    outdated_side: {"policy_id": str(OUTDATED_POLICY_ID)},
                    other_side: {"policy_id": str(OTHER_POLICY_ID)},
                }
            )
        )


def test_a_policy_the_running_catalog_could_not_check_is_sent() -> None:
    client = RecordingSimulationService()

    submissions(lambda: client).submit_report(
        report_input(reform={"policy_id": str(UNCHECKED_POLICY_ID)})
    )
    submissions(lambda: client).submit_simulation(
        simulation_input(policy_id=str(UNCHECKED_POLICY_ID))
    )

    assert len(client.reports) == 1
    assert len(client.simulations) == 1


@pytest.mark.parametrize(
    "error",
    [
        MetadataCatalogUnavailableError("the v2 metadata catalog cannot be queried"),
        OperationalError("SELECT 1", {}, Exception("connection refused")),
    ],
    ids=["catalog", "database"],
)
def test_a_policy_check_that_cannot_read_storage_is_storage_unavailable(
    error: Exception,
) -> None:
    service = submissions(unconfigured_client, StoredPolicies(error=error))

    with pytest.raises(SubmissionStorageError) as unavailable:
        service.submit_report(report_input())

    assert unavailable.value.__cause__ is error
