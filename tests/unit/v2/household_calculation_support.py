"""Fakes and records shared by the household calculation tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.households.types import HouseholdRead
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.types import (
    PolicyParameterValueRead,
    PolicyRead,
)
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError

HOUSEHOLD_ID = UUID("00000000-0000-4000-8000-0000000000a1")
POLICY_ID = UUID("00000000-0000-4000-8000-0000000000b1")
CALCULATION_ID = UUID("00000000-0000-4000-8000-0000000000c1")
SIMULATION_ID = UUID("00000000-0000-4000-8000-0000000000d1")
CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000e1")
POLICYENGINE_VERSION = "6.10.0"
CREATED_AT = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
SPM_CHOICE = {"scenario": "ce_trend", "geography_kind": "national"}
HOUSEHOLD_DATA = {
    "people": [
        {
            "id": "person-1",
            "values": {"age": {"2026": 40}, "employment_income": {"2026": 30000}},
            "memberships": {
                "household": "household-1",
                "family": "family-1",
                "tax_unit": "tax_unit-1",
                "spm_unit": "spm_unit-1",
                "marital_unit": "marital_unit-1",
            },
        }
    ],
    "household": [{"id": "household-1", "values": {"state_name": {"2026": "CA"}}}],
    "family": [{"id": "family-1", "values": {}}],
    "tax_unit": [{"id": "tax_unit-1", "values": {}}],
    "spm_unit": [{"id": "spm_unit-1", "values": {}}],
    "marital_unit": [{"id": "marital_unit-1", "values": {}}],
    "spm": SPM_CHOICE,
}
SITUATION = {
    "people": {"person-1": {"age": {"2026": 40}, "employment_income": {"2026": 30000}}},
    "households": {
        "household-1": {"members": ["person-1"], "state_name": {"2026": "CA"}}
    },
    "families": {"family-1": {"members": ["person-1"]}},
    "tax_units": {"tax_unit-1": {"members": ["person-1"]}},
    "spm_units": {"spm_unit-1": {"members": ["person-1"]}},
    "marital_units": {"marital_unit-1": {"members": ["person-1"]}},
}
SPM_CONFIG = {
    "forecast_content_sha256": "3d" * 32,
    "scenario": "ce_trend",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
SPM_PROVENANCE = {"schema_version": "canonical-spm-provenance-v2", "years": ["2026"]}
BUNDLE = {
    "policyengine_version": POLICYENGINE_VERSION,
    "core_package_version": "3.33.0",
    "country_package_name": "policyengine-us",
    "country_package_version": "1.450.0",
    "bundle_manifest_sha256": "a" * 64,
}


def simulation_calculation(**changes: object) -> dict[str, Any]:
    """Return the simulation service's answer for a running calculation."""
    answer: dict[str, Any] = {
        "calculation_id": str(CALCULATION_ID),
        "simulation_id": str(SIMULATION_ID),
        "country": "us",
        "household_id": str(HOUSEHOLD_ID),
        "policy_id": str(POLICY_ID),
        "options": {},
        "catalog_version_id": str(CATALOG_VERSION_ID),
        "year": 2026,
        "attempt": 1,
        "trigger": "initial",
        "status": "running",
        "created_at": CREATED_AT.isoformat(),
        "dispatched_at": CREATED_AT.isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
    }
    answer.update(changes)
    return answer


def succeeded_calculation() -> dict[str, Any]:
    """Return the simulation service's answer once the calculation succeeded."""
    return simulation_calculation(
        status="succeeded",
        completed_at=CREATED_AT.isoformat(),
        result={
            "household": {
                **SITUATION,
                "households": {
                    "household-1": {
                        "members": ["person-1"],
                        "state_name": {"2026": "CA"},
                        "household_net_income": {"2026": 27000.5},
                    }
                },
            },
            "warnings": ["The input `age_group` is deprecated and was ignored."],
            "spm_config": SPM_CONFIG,
            "spm_provenance": SPM_PROVENANCE,
            "bundle": BUNDLE,
        },
    )


def household_read(*, default_year: int | None = 2026) -> HouseholdRead:
    """Return the stored US household."""
    return HouseholdRead(
        id=HOUSEHOLD_ID,
        country_id="us",
        default_year=default_year,
        household_data=HOUSEHOLD_DATA,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def policy_read() -> PolicyRead:
    """Return the stored US reform with one parameter value."""
    return PolicyRead(
        id=POLICY_ID,
        country_id="us",
        tax_benefit_model_id=CATALOG_VERSION_ID,
        tax_benefit_model_version_id=CATALOG_VERSION_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        parameter_values=(
            PolicyParameterValueRead(
                id=POLICY_ID,
                parameter_id=POLICY_ID,
                parameter_name="gov.irs.credits.ctc.amount.base[0].amount",
                value=3000,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=None,
            ),
        ),
    )


@dataclass
class FakeCountries:
    """The countries table: the US with every calculation, the UK households only."""

    rows: tuple[CountryRead, ...] = (
        CountryRead(id="uk", household_enabled=True, society_wide_enabled=False),
        CountryRead(id="us", household_enabled=True, society_wide_enabled=True),
    )

    def list_countries(self) -> list[CountryRead]:
        """Return every row."""
        return list(self.rows)


class FakeHouseholds:
    """Stored households by country and ID."""

    def __init__(self) -> None:
        """Hold the stored US household."""
        self.households = {("us", HOUSEHOLD_ID): household_read()}
        self.calls: list[tuple[str, UUID]] = []

    def get_household(self, *, country_id: str, household_id: UUID) -> HouseholdRead:
        """Return the household or raise HouseholdNotFoundError."""
        self.calls.append((country_id, household_id))
        household = self.households.get((country_id, household_id))
        if household is None:
            msg = f"Household {household_id} not found."
            raise HouseholdNotFoundError(msg)
        return household


class FakePolicies:
    """Stored policies by country and ID."""

    def __init__(self) -> None:
        """Hold the stored US reform."""
        self.policies = {("us", POLICY_ID): policy_read()}

    def get_policy(self, *, country_id: str, policy_id: UUID) -> PolicyRead:
        """Return the policy or raise PolicyNotFoundError."""
        policy = self.policies.get((country_id, policy_id))
        if policy is None:
            msg = f"Policy {policy_id} not found."
            raise PolicyNotFoundError(msg)
        return policy


class FakeCatalogs:
    """Each country's current catalog version, and whether it was closed."""

    def __init__(self) -> None:
        """Start open."""
        self.closed = False

    def get_model_by_country(self, country_id: str) -> SimpleNamespace:
        """Return the running catalog version's ID and PolicyEngine.py version."""
        return SimpleNamespace(
            policyengine_version=POLICYENGINE_VERSION,
            model_version=SimpleNamespace(id=CATALOG_VERSION_ID),
            country_id=country_id,
        )

    def close(self) -> None:
        """Record the close."""
        self.closed = True


class FakeSimulation:
    """The simulation service's household routes, as scripted answers."""

    def __init__(self) -> None:
        """Answer submissions with a running calculation."""
        self.submissions: list[dict[str, Any]] = []
        self.answer: dict[str, Any] = simulation_calculation()
        self.read_answers: dict[UUID, dict[str, Any]] = {}
        self.error: Exception | None = None

    def submit(self, submission: dict[str, Any]) -> dict[str, Any]:
        """Record the submission and answer it."""
        self.submissions.append(submission)
        if self.error is not None:
            raise self.error
        return self.answer

    def read(self, calculation_id: UUID) -> dict[str, Any] | None:
        """Return the scripted calculation, or None."""
        if self.error is not None:
            raise self.error
        return self.read_answers.get(calculation_id)
