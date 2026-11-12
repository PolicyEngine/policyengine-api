"""Stored rows and stand-in services shared by the household calculation tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationAccepted,
    HouseholdCalculationInput,
)
from policyengine_api.services.v2.households.types import HouseholdRead
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.types import (
    CheckedPolicyRead,
    PolicyParameterValueRead,
)
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from tests.fixtures.household_calculation_documents import JOB_ID

HOUSEHOLD_ID = UUID("00000000-0000-4000-8000-0000000000a1")
POLICY_ID = UUID("00000000-0000-4000-8000-0000000000b1")
MODEL_ID = UUID("00000000-0000-4000-8000-0000000000d1")
CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000e1")
CREATED_AT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
REFORMED_PARAMETER = "gov.irs.credits.ctc.amount.base[0].amount"


def household_read(*, default_year: int | None = 2026) -> HouseholdRead:
    """Return the stored US household."""
    return HouseholdRead(
        id=HOUSEHOLD_ID,
        country_id="us",
        default_year=default_year,
        household_data={"people": [], "household": []},
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def policy_read(
    *, missing_parameters: tuple[str, ...] | None = ()
) -> CheckedPolicyRead:
    """Return the stored US reform, checked against the running catalog."""
    return CheckedPolicyRead(
        id=POLICY_ID,
        country_id="us",
        tax_benefit_model_id=MODEL_ID,
        tax_benefit_model_version_id=CATALOG_VERSION_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        parameter_values=(
            PolicyParameterValueRead(
                id=POLICY_ID,
                parameter_id=POLICY_ID,
                parameter_name=REFORMED_PARAMETER,
                value=3000,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=None,
            ),
        ),
        missing_parameters=missing_parameters,
    )


def calculation_input(**changes: object) -> HouseholdCalculationInput:
    """Return a calculation of the stored household under the stored reform."""
    fields: dict[str, object] = {
        "country_id": "us",
        "household_id": HOUSEHOLD_ID,
        "policy_id": POLICY_ID,
    }
    fields.update(changes)
    return HouseholdCalculationInput.model_validate(fields)


@dataclass
class FakeCountries:
    """The countries table: the US with every calculation, the UK households only."""

    rows: tuple[CountryRead, ...] = (
        CountryRead(id="uk", household_enabled=True, society_wide_enabled=False),
        CountryRead(id="us", household_enabled=True, society_wide_enabled=True),
    )
    error: Exception | None = None

    def list_countries(self) -> list[CountryRead]:
        """Return every row, or raise the scripted error."""
        if self.error is not None:
            raise self.error
        return list(self.rows)


@dataclass
class FakeHouseholds:
    """Stored households by country and ID; records each read."""

    households: dict[tuple[str, UUID], HouseholdRead] = field(
        default_factory=lambda: {("us", HOUSEHOLD_ID): household_read()}
    )
    reads: list[tuple[str, UUID]] = field(default_factory=list)

    def get_household(self, *, country_id: str, household_id: UUID) -> HouseholdRead:
        """Return the household or raise HouseholdNotFoundError."""
        self.reads.append((country_id, household_id))
        household = self.households.get((country_id, household_id))
        if household is None:
            msg = f"Household {household_id} not found."
            raise HouseholdNotFoundError(msg)
        return household


@dataclass
class FakePolicies:
    """Stored policies by country and ID; records each read."""

    policies: dict[tuple[str, UUID], CheckedPolicyRead] = field(
        default_factory=lambda: {("us", POLICY_ID): policy_read()}
    )
    reads: list[tuple[str, UUID]] = field(default_factory=list)

    def get_policy(self, *, country_id: str, policy_id: UUID) -> CheckedPolicyRead:
        """Return the policy or raise PolicyNotFoundError."""
        self.reads.append((country_id, policy_id))
        policy = self.policies.get((country_id, policy_id))
        if policy is None:
            msg = f"Policy {policy_id} not found."
            raise PolicyNotFoundError(msg)
        return policy


@dataclass
class FakeSimulation:
    """The simulation service's household submission, as a scripted answer."""

    answer: HouseholdCalculationAccepted = field(
        default_factory=lambda: HouseholdCalculationAccepted(
            calculation_id=JOB_ID, status="pending"
        )
    )
    error: Exception | None = None
    submissions: list[HouseholdCalculationInput] = field(default_factory=list)

    def submit(
        self, calculation: HouseholdCalculationInput
    ) -> HouseholdCalculationAccepted:
        """Record the submission and answer it, or raise the scripted error."""
        self.submissions.append(calculation)
        if self.error is not None:
            raise self.error
        return self.answer
