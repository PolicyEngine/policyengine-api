"""Check household reports before the simulation service creates them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.households.types import HouseholdRead
from policyengine_api.services.v2.households.validators import (
    HouseholdNotFoundError,
)
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
    PolicyParametersMissingError,
)
from policyengine_api.services.v2.simulation_service.services import (
    SimulationSubmissionService,
)
from policyengine_api.services.v2.simulation_service.types import (
    HouseholdReportCreationInput,
    SubmittedReport,
)
from policyengine_api.services.v2.simulation_service.validators import (
    HouseholdCalculationsUnsupportedError,
    SubmissionStorageError,
)
from tests.unit.v2.test_simulation_submissions import (
    HOUSEHOLD_ONLY_UK,
    OTHER_POLICY_ID,
    OUTDATED_POLICY_ID,
    REMOVED_PARAMETERS,
    SECOND_OUTDATED_POLICY_ID,
    SERVED_COUNTRIES,
    STORED_POLICY_ID,
    StoredCountries,
    StoredPolicies,
)

HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-00000000d001")
OTHER_HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-00000000d002")
STORED_AT = datetime(2026, 11, 13, tzinfo=UTC)
# A country whose countries row offers economy reports but no household
# calculations.
ECONOMY_ONLY_US = [
    CountryRead(id="uk", household_enabled=True, society_wide_enabled=True),
    CountryRead(id="us", household_enabled=False, society_wide_enabled=True),
]


@dataclass
class StoredHouseholds:
    """HOUSEHOLD_ID, stored in every country; any other household is not stored.

    With ``error``, every read raises it, as a database that cannot be read
    does.
    """

    error: Exception | None = None
    asked: list[tuple[str, UUID]] = field(default_factory=list)

    def get_household(self, *, country_id: str, household_id: UUID) -> HouseholdRead:
        self.asked.append((country_id, household_id))
        if self.error is not None:
            raise self.error
        if household_id != HOUSEHOLD_ID:
            msg = f"Household {household_id} was not found"
            raise HouseholdNotFoundError(msg)
        return HouseholdRead(
            id=household_id,
            country_id=country_id,
            default_year=2026,
            household_data={"people": {"you": {"age": {"2026": 40}}}},
            created_at=STORED_AT,
            updated_at=STORED_AT,
        )


@dataclass
class RecordingHouseholdReportService:
    """The simulation service's client, recording the household reports it is sent."""

    household_reports: list[HouseholdReportCreationInput] = field(default_factory=list)

    def submit_household_report(
        self, report: HouseholdReportCreationInput
    ) -> SubmittedReport:
        self.household_reports.append(report)
        return SubmittedReport(report_id=uuid4(), report_run_id=uuid4())


def unconfigured_client() -> RecordingHouseholdReportService:
    msg = "the simulation service must not be asked"
    raise AssertionError(msg)


def household_report_input(**changes: Any) -> HouseholdReportCreationInput:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "household",
        "label": "My household under the reform",
        "household_id": str(HOUSEHOLD_ID),
        "year": 2026,
        "baseline": {},
        "reform": {"policy_id": str(STORED_POLICY_ID)},
    }
    return HouseholdReportCreationInput.model_validate({**values, **changes})


def household_submissions(
    client_factory: Any,
    *,
    countries: list[CountryRead] = SERVED_COUNTRIES,
    households: StoredHouseholds | None = None,
    policies: StoredPolicies | None = None,
) -> SimulationSubmissionService:
    return SimulationSubmissionService(
        countries=StoredCountries(countries=countries),
        households=households or StoredHouseholds(),
        policies=policies or StoredPolicies(),
        client_factory=client_factory,
    )


def test_a_household_report_is_sent_once_its_country_household_and_policies_pass() -> (
    None
):
    client = RecordingHouseholdReportService()
    households = StoredHouseholds()
    policies = StoredPolicies()
    report = household_report_input(
        baseline={"policy_id": str(STORED_POLICY_ID)}, add_missing_variables=True
    )

    submitted = household_submissions(
        lambda: client, households=households, policies=policies
    ).submit_household_report(report)

    assert client.household_reports == [report]
    assert isinstance(submitted, SubmittedReport)
    assert households.asked == [("us", HOUSEHOLD_ID)]
    assert policies.asked == [("us", STORED_POLICY_ID)]


def test_a_household_only_country_can_submit_household_reports() -> None:
    client = RecordingHouseholdReportService()
    report = household_report_input(country_id="uk")

    household_submissions(
        lambda: client, countries=HOUSEHOLD_ONLY_UK
    ).submit_household_report(report)

    assert client.household_reports == [report]


@pytest.mark.parametrize(
    "countries",
    [
        pytest.param(ECONOMY_ONLY_US, id="household-calculations-off"),
        pytest.param(SERVED_COUNTRIES[:1], id="no-countries-row"),
    ],
)
def test_a_country_without_household_calculations_is_refused_before_anything_is_read(
    countries: list[CountryRead],
) -> None:
    households = StoredHouseholds()
    policies = StoredPolicies()
    service = household_submissions(
        unconfigured_client,
        countries=countries,
        households=households,
        policies=policies,
    )

    with pytest.raises(HouseholdCalculationsUnsupportedError, match="'us'"):
        service.submit_household_report(household_report_input())
    assert households.asked == []
    assert policies.asked == []


def test_a_household_not_stored_in_the_country_is_refused_before_the_policies() -> None:
    policies = StoredPolicies()
    service = household_submissions(unconfigured_client, policies=policies)

    with pytest.raises(HouseholdNotFoundError, match=str(OTHER_HOUSEHOLD_ID)):
        service.submit_household_report(
            household_report_input(household_id=str(OTHER_HOUSEHOLD_ID))
        )
    assert policies.asked == []


@pytest.mark.parametrize("side", ["baseline", "reform"])
def test_a_household_report_naming_a_policy_not_stored_in_the_country_is_refused(
    side: str,
) -> None:
    service = household_submissions(unconfigured_client)

    with pytest.raises(PolicyNotFoundError, match=str(OTHER_POLICY_ID)):
        service.submit_household_report(
            household_report_input(**{side: {"policy_id": str(OTHER_POLICY_ID)}})
        )


def test_the_baselines_policy_with_missing_parameters_is_refused_first() -> None:
    service = household_submissions(unconfigured_client)

    with pytest.raises(PolicyParametersMissingError) as refused:
        service.submit_household_report(
            household_report_input(
                baseline={"policy_id": str(OUTDATED_POLICY_ID)},
                reform={"policy_id": str(SECOND_OUTDATED_POLICY_ID)},
            )
        )

    assert refused.value.policy_id == OUTDATED_POLICY_ID
    assert refused.value.missing_parameters == REMOVED_PARAMETERS


def test_a_policy_not_stored_comes_before_one_with_missing_parameters() -> None:
    service = household_submissions(unconfigured_client)

    with pytest.raises(PolicyNotFoundError):
        service.submit_household_report(
            household_report_input(
                baseline={"policy_id": str(OUTDATED_POLICY_ID)},
                reform={"policy_id": str(OTHER_POLICY_ID)},
            )
        )


def test_a_report_of_the_baseline_alone_checks_only_the_baselines_policy() -> None:
    client = RecordingHouseholdReportService()
    policies = StoredPolicies()
    report = household_report_input(
        baseline={"policy_id": str(STORED_POLICY_ID)}, reform=None
    )

    household_submissions(lambda: client, policies=policies).submit_household_report(
        report
    )

    assert policies.asked == [("us", STORED_POLICY_ID)]
    assert client.household_reports[0].reform is None


@pytest.mark.parametrize(
    ("households", "policies"),
    [
        pytest.param(
            StoredHouseholds(error=OperationalError("SELECT", {}, Exception())),
            StoredPolicies(),
            id="households-unreadable",
        ),
        pytest.param(
            StoredHouseholds(),
            StoredPolicies(error=OperationalError("SELECT", {}, Exception())),
            id="policies-unreadable",
        ),
        pytest.param(
            StoredHouseholds(),
            StoredPolicies(error=MetadataCatalogUnavailableError("no catalog")),
            id="catalog-unreadable",
        ),
    ],
)
def test_storage_that_cannot_be_read_while_checking_is_a_storage_failure(
    households: StoredHouseholds, policies: StoredPolicies
) -> None:
    service = household_submissions(
        unconfigured_client, households=households, policies=policies
    )

    with pytest.raises(SubmissionStorageError):
        service.submit_household_report(household_report_input())


def test_a_household_report_without_a_reform_is_of_the_baseline_alone() -> None:
    report = HouseholdReportCreationInput.model_validate(
        {
            "country_id": "us",
            "kind": "household",
            "label": "My household",
            "household_id": str(HOUSEHOLD_ID),
            "year": 2026,
            "baseline": {},
        }
    )

    assert report.reform is None
    assert report.add_missing_variables is False
    assert report.description is None


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"label": ""}, id="empty-label"),
        pytest.param({"year": 1899}, id="year-before-1900"),
        pytest.param({"year": 2201}, id="year-after-2200"),
        pytest.param({"add_missing_variables": "true"}, id="option-not-a-boolean"),
        pytest.param({"baseline": {"dynamic_id": str(uuid4())}}, id="dynamic"),
        pytest.param({"region_code": "us"}, id="region"),
        pytest.param({"household_id": "not-a-uuid"}, id="household-not-a-uuid"),
        pytest.param({"kind": "economy"}, id="another-kind"),
    ],
)
def test_a_household_report_outside_its_schema_is_refused(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        household_report_input(**changes)


@pytest.mark.parametrize("missing", ["label", "household_id", "year", "baseline"])
def test_a_household_report_needs_its_label_household_year_and_baseline(
    missing: str,
) -> None:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "household",
        "label": "My household",
        "household_id": str(HOUSEHOLD_ID),
        "year": 2026,
        "baseline": {},
    }
    del values[missing]

    with pytest.raises(ValidationError):
        HouseholdReportCreationInput.model_validate(values)
