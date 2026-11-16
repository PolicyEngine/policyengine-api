"""Check a stored report's country and policies before running it again."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
)
from policyengine_api.services.v2.policies.types import CheckedPolicyRead
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
    PolicyParametersMissingError,
)
from policyengine_api.services.v2.simulation_service.services import (
    SimulationSubmissionService,
)
from policyengine_api.services.v2.simulation_service.types import (
    ReportRerunInput,
    ReportRerunKind,
)
from policyengine_api.services.v2.simulation_service.validators import (
    EconomyCalculationsUnsupportedError,
    SubmissionStorageError,
)

REPORT_ID = UUID("00000000-0000-0000-0000-00000000e001")
STORED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000e002")
OUTDATED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000e003")
REMOVED_PARAMETERS = ("gov.example.removed_amount",)
# Each stored policy's parameters the running catalog version lacks.
MISSING_PARAMETERS: dict[UUID, tuple[str, ...]] = {
    STORED_POLICY_ID: (),
    OUTDATED_POLICY_ID: REMOVED_PARAMETERS,
}
STORED_AT = datetime(2026, 11, 13, tzinfo=UTC)


@dataclass
class StoredCountries:
    society_wide_enabled: bool = True
    household_enabled: bool = True

    def list_countries(self) -> list[CountryRead]:
        return [
            CountryRead(
                id="us",
                household_enabled=self.household_enabled,
                society_wide_enabled=self.society_wide_enabled,
            )
        ]


@dataclass
class UnreadableCountries:
    """The countries, which cannot be read."""

    error: Exception

    def list_countries(self) -> list[CountryRead]:
        raise self.error


@dataclass
class StoredPolicies:
    """The policies in MISSING_PARAMETERS, stored in every country."""

    error: Exception | None = None
    asked: list[UUID] = field(default_factory=list)

    def get_policy(self, *, country_id: str, policy_id: UUID) -> CheckedPolicyRead:
        self.asked.append(policy_id)
        if self.error is not None:
            raise self.error
        if policy_id not in MISSING_PARAMETERS:
            msg = f"Policy {policy_id} was not found"
            raise PolicyNotFoundError(msg)
        return CheckedPolicyRead(
            id=policy_id,
            country_id=country_id,
            tax_benefit_model_id=uuid4(),
            tax_benefit_model_version_id=uuid4(),
            created_at=STORED_AT,
            updated_at=STORED_AT,
            parameter_values=(),
            missing_parameters=MISSING_PARAMETERS[policy_id],
        )


@dataclass
class RecordingSimulationService:
    reruns: list[ReportRerunInput] = field(default_factory=list)

    def rerun_report(self, rerun: ReportRerunInput) -> None:
        self.reruns.append(rerun)


class UnreadHouseholds:
    """The stored households, which a re-run never reads.

    A household report's household is stored as long as the report names it.
    """

    def get_household(self, *, country_id: str, household_id: UUID) -> object:
        msg = "a re-run must not read a household"
        raise AssertionError(msg)


def unconfigured_client() -> RecordingSimulationService:
    msg = "the simulation service must not be asked"
    raise AssertionError(msg)


def rerun_input(
    *policy_ids: UUID | None, kind: ReportRerunKind = "economy"
) -> ReportRerunInput:
    return ReportRerunInput(
        country_id="us",
        report_id=REPORT_ID,
        kind=kind,
        force=True,
        policy_ids=policy_ids,
    )


def test_a_rerun_is_sent_once_its_country_and_policies_are_checked() -> None:
    client = RecordingSimulationService()
    policies = StoredPolicies()
    service = SimulationSubmissionService(
        countries=StoredCountries(),
        households=UnreadHouseholds(),
        policies=policies,
        client_factory=lambda: client,
    )
    rerun = rerun_input(None, STORED_POLICY_ID)

    service.rerun_report(rerun)

    assert client.reruns == [rerun]
    assert policies.asked == [STORED_POLICY_ID]


def test_a_rerun_in_a_household_only_country_is_refused_before_sending() -> None:
    service = SimulationSubmissionService(
        countries=StoredCountries(society_wide_enabled=False),
        households=UnreadHouseholds(),
        policies=StoredPolicies(),
        client_factory=unconfigured_client,
    )

    with pytest.raises(EconomyCalculationsUnsupportedError, match="'us'"):
        service.rerun_report(rerun_input(None, STORED_POLICY_ID))


def test_a_rerun_naming_a_policy_no_longer_stored_is_refused() -> None:
    missing_policy_id = uuid4()
    service = SimulationSubmissionService(
        countries=StoredCountries(),
        households=UnreadHouseholds(),
        policies=StoredPolicies(),
        client_factory=unconfigured_client,
    )

    with pytest.raises(PolicyNotFoundError, match=str(missing_policy_id)):
        service.rerun_report(rerun_input(None, missing_policy_id))


def test_a_rerun_whose_policy_sets_parameters_the_catalog_lacks_is_refused() -> None:
    service = SimulationSubmissionService(
        countries=StoredCountries(),
        households=UnreadHouseholds(),
        policies=StoredPolicies(),
        client_factory=unconfigured_client,
    )

    with pytest.raises(PolicyParametersMissingError) as refusal:
        service.rerun_report(rerun_input(STORED_POLICY_ID, OUTDATED_POLICY_ID))

    assert refusal.value.missing_parameters == REMOVED_PARAMETERS


def test_a_rerun_whose_policy_check_cannot_read_storage_is_storage_unavailable() -> (
    None
):
    error = OperationalError("SELECT 1", {}, Exception("connection refused"))
    service = SimulationSubmissionService(
        countries=StoredCountries(),
        households=UnreadHouseholds(),
        policies=StoredPolicies(error=error),
        client_factory=unconfigured_client,
    )

    with pytest.raises(SubmissionStorageError) as unavailable:
        service.rerun_report(rerun_input(None, STORED_POLICY_ID))

    assert unavailable.value.__cause__ is error


@pytest.mark.parametrize("kind", ["economy", "budget_window"])
def test_a_rerun_where_only_households_are_calculated_is_refused_for_economy_kinds(
    kind: ReportRerunKind,
) -> None:
    service = SimulationSubmissionService(
        countries=StoredCountries(society_wide_enabled=False),
        households=UnreadHouseholds(),
        policies=StoredPolicies(),
        client_factory=unconfigured_client,
    )

    with pytest.raises(EconomyCalculationsUnsupportedError, match="'us'"):
        service.rerun_report(rerun_input(None, STORED_POLICY_ID, kind=kind))


def test_a_household_reports_rerun_is_sent_where_only_households_are_calculated() -> (
    None
):
    client = RecordingSimulationService()
    policies = StoredPolicies()
    service = SimulationSubmissionService(
        countries=StoredCountries(society_wide_enabled=False),
        households=UnreadHouseholds(),
        policies=policies,
        client_factory=lambda: client,
    )
    rerun = rerun_input(None, STORED_POLICY_ID, kind="household")

    service.rerun_report(rerun)

    assert client.reruns == [rerun]
    assert policies.asked == [STORED_POLICY_ID]


def test_a_household_report_of_the_baseline_alone_checks_the_baseline_policy() -> None:
    client = RecordingSimulationService()
    policies = StoredPolicies()
    service = SimulationSubmissionService(
        countries=StoredCountries(society_wide_enabled=False),
        households=UnreadHouseholds(),
        policies=policies,
        client_factory=lambda: client,
    )
    rerun = rerun_input(STORED_POLICY_ID, None, kind="household")

    service.rerun_report(rerun)

    assert client.reruns == [rerun]
    assert policies.asked == [STORED_POLICY_ID]


def test_a_household_reports_rerun_without_household_calculations_is_refused() -> None:
    policies = StoredPolicies()
    service = SimulationSubmissionService(
        countries=StoredCountries(household_enabled=False),
        households=UnreadHouseholds(),
        policies=policies,
        client_factory=unconfigured_client,
    )

    with pytest.raises(HouseholdCalculationCountryError, match="country us"):
        service.rerun_report(rerun_input(None, STORED_POLICY_ID, kind="household"))

    assert policies.asked == []


def test_a_household_reports_rerun_checks_its_policies_as_a_new_one_does() -> None:
    service = SimulationSubmissionService(
        countries=StoredCountries(society_wide_enabled=False),
        households=UnreadHouseholds(),
        policies=StoredPolicies(),
        client_factory=unconfigured_client,
    )

    with pytest.raises(PolicyParametersMissingError) as refusal:
        service.rerun_report(rerun_input(None, OUTDATED_POLICY_ID, kind="household"))

    assert refusal.value.missing_parameters == REMOVED_PARAMETERS


def test_a_household_reports_rerun_whose_countries_cannot_be_read_is_unavailable() -> (
    None
):
    error = OperationalError("SELECT 1", {}, Exception("connection refused"))
    service = SimulationSubmissionService(
        countries=UnreadableCountries(error),
        households=UnreadHouseholds(),
        policies=StoredPolicies(),
        client_factory=unconfigured_client,
    )

    with pytest.raises(SubmissionStorageError) as unavailable:
        service.rerun_report(rerun_input(None, STORED_POLICY_ID, kind="household"))

    assert unavailable.value.__cause__ is error
