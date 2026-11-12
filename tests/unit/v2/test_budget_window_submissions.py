"""Check budget windows before the simulation service creates them.

A budget window is checked as an economy report is: the country must have
economy calculations, and each policy it names must be stored in the
country with every parameter it sets in the running catalog version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

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
    BudgetWindowReportCreationInput,
    SubmittedBudgetWindow,
)
from policyengine_api.services.v2.simulation_service.validators import (
    EconomyCalculationsUnsupportedError,
)

STORED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c101")
OUTDATED_POLICY_ID = UUID("00000000-0000-0000-0000-00000000c102")
REMOVED_PARAMETERS = ("gov.example.removed_amount",)
MISSING_PARAMETERS: dict[UUID, tuple[str, ...]] = {
    STORED_POLICY_ID: (),
    OUTDATED_POLICY_ID: REMOVED_PARAMETERS,
}
STORED_AT = datetime(2026, 11, 12, tzinfo=UTC)


@dataclass
class StoredCountries:
    """The US with economy calculations, and the UK as a household-only country."""

    def list_countries(self) -> list[CountryRead]:
        return [
            CountryRead(id="uk", household_enabled=True, society_wide_enabled=False),
            CountryRead(id="us", household_enabled=True, society_wide_enabled=True),
        ]


@dataclass
class StoredPolicies:
    """The policies in MISSING_PARAMETERS, stored in every country."""

    asked: list[tuple[str, UUID]] = field(default_factory=list)

    def get_policy(self, *, country_id: str, policy_id: UUID) -> CheckedPolicyRead:
        self.asked.append((country_id, policy_id))
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
    """The simulation service's client, recording the budget windows it is sent."""

    windows: list[BudgetWindowReportCreationInput] = field(default_factory=list)

    def submit_budget_window(
        self, report: BudgetWindowReportCreationInput
    ) -> SubmittedBudgetWindow:
        self.windows.append(report)
        return SubmittedBudgetWindow(report_id=uuid4(), budget_window_run_id=uuid4())


def window_input(**changes: Any) -> BudgetWindowReportCreationInput:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "budget_window",
        "label": "Reform, ten years",
        "year": 2026,
        "budget_window_size": 10,
        "region_code": "us",
        "baseline": {"policy_id": str(STORED_POLICY_ID)},
        "reform": {"policy_id": str(STORED_POLICY_ID)},
    }
    return BudgetWindowReportCreationInput.model_validate({**values, **changes})


def submissions(
    client: RecordingSimulationService, policies: StoredPolicies
) -> SimulationSubmissionService:
    return SimulationSubmissionService(
        countries=StoredCountries(), policies=policies, client_factory=lambda: client
    )


def test_a_budget_window_is_sent_once_its_country_and_policies_are_checked() -> None:
    client = RecordingSimulationService()
    policies = StoredPolicies()
    window = window_input()

    submitted = submissions(client, policies).submit_budget_window(window)

    assert client.windows == [window]
    assert isinstance(submitted, SubmittedBudgetWindow)
    assert policies.asked == [("us", STORED_POLICY_ID)]


def test_a_household_only_countrys_budget_window_is_refused_before_sending() -> None:
    client = RecordingSimulationService()

    with pytest.raises(EconomyCalculationsUnsupportedError):
        submissions(client, StoredPolicies()).submit_budget_window(
            window_input(country_id="uk", region_code="uk")
        )

    assert client.windows == []


def test_a_budget_window_naming_an_unstored_policy_is_refused() -> None:
    client = RecordingSimulationService()

    with pytest.raises(PolicyNotFoundError):
        submissions(client, StoredPolicies()).submit_budget_window(
            window_input(reform={"policy_id": str(uuid4())})
        )

    assert client.windows == []


def test_a_budget_window_whose_policy_sets_missing_parameters_is_refused() -> None:
    client = RecordingSimulationService()

    with pytest.raises(PolicyParametersMissingError) as raised:
        submissions(client, StoredPolicies()).submit_budget_window(
            window_input(reform={"policy_id": str(OUTDATED_POLICY_ID)})
        )

    assert raised.value.missing_parameters == REMOVED_PARAMETERS
    assert client.windows == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        pytest.param(
            {"budget_window_size": 0}, "greater than or equal to 1", id="none"
        ),
        pytest.param(
            {"budget_window_size": 76}, "less than or equal to 75", id="over-75"
        ),
        pytest.param(
            {"year": 2195, "budget_window_size": 7}, "end in 2200 or earlier", id="late"
        ),
        pytest.param({"include_cliffs": True}, "Extra inputs", id="cliffs"),
        pytest.param({"spm": None}, "spm must be an object", id="null-spm"),
    ],
)
def test_a_window_the_tables_cannot_hold_is_refused(
    changes: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        window_input(**changes)


def test_a_window_may_end_in_2200() -> None:
    window = window_input(year=2191, budget_window_size=10)

    assert (window.year, window.budget_window_size) == (2191, 10)
