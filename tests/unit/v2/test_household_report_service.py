"""The household report service.

It runs with SQLite countries and catalog rows, fake stored households and
policies, and a fake Simulation Entrypoint.
"""

from __future__ import annotations

import pytest

from policyengine_api.services.v2.household_reports.types import (
    HouseholdPolicyChoice,
    HouseholdReportFields,
    HouseholdReportSubmission,
)
from policyengine_api.services.v2.household_reports.validators import (
    HouseholdReportsUnsupportedError,
    HouseholdReportYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ReportStatus,
    SimulationRequestRefusedError,
)
from tests.unit.v2.economy_report_support import CURRENT_POLICYENGINE_VERSION
from tests.unit.v2.household_report_support import (
    HOUSEHOLD_ID,
    HOUSEHOLD_ONLY_HOUSEHOLD_ID,
    HOUSEHOLD_REFORM_POLICY_ID,
    OLDER_CATALOG_VERSION_ID,
    OLDER_POLICYENGINE_VERSION,
    UNKNOWN_CATALOG_VERSION_ID,
    FakeHouseholdReportSimulation,
    FakeHouseholds,
    household_report_service,
    stored_household,
)


def _fields(*, reform_policy_id=HOUSEHOLD_REFORM_POLICY_ID, household_id=HOUSEHOLD_ID):
    return HouseholdReportFields(
        kind="household",
        household_id=household_id,
        baseline=HouseholdPolicyChoice(),
        reform=(
            None
            if reform_policy_id is None
            else HouseholdPolicyChoice(policy_id=reform_policy_id)
        ),
    )


def test_a_report_is_submitted_by_ids_on_the_current_version() -> None:
    simulation = FakeHouseholdReportSimulation()

    report = household_report_service(simulation).submit_report(
        country_id="us", report_input=_fields()
    )

    assert simulation.calls == [
        (
            "submit_report",
            HouseholdReportSubmission(
                country_id="us",
                policyengine_version=CURRENT_POLICYENGINE_VERSION,
                household_id=HOUSEHOLD_ID,
                baseline=HouseholdPolicyChoice(),
                reform=HouseholdPolicyChoice(policy_id=HOUSEHOLD_REFORM_POLICY_ID),
            ),
        )
    ]
    assert report.status is ReportStatus.PENDING
    assert report.run is not None
    assert report.run.policyengine_version == CURRENT_POLICYENGINE_VERSION


def test_a_run_names_the_policyengine_version_of_its_catalog_version() -> None:
    simulation = FakeHouseholdReportSimulation()
    simulation.next_catalog_version_id = OLDER_CATALOG_VERSION_ID

    report = household_report_service(simulation).submit_report(
        country_id="us", report_input=_fields()
    )

    assert report.run is not None
    assert report.run.policyengine_version == OLDER_POLICYENGINE_VERSION


def test_a_run_on_a_catalog_version_the_public_api_lacks_names_no_version() -> None:
    simulation = FakeHouseholdReportSimulation()
    simulation.next_catalog_version_id = UNKNOWN_CATALOG_VERSION_ID

    report = household_report_service(simulation).submit_report(
        country_id="us", report_input=_fields()
    )

    assert report.run is not None
    assert report.run.policyengine_version is None


def test_a_baseline_only_report_sends_no_reform() -> None:
    simulation = FakeHouseholdReportSimulation()

    report = household_report_service(simulation).submit_report(
        country_id="us", report_input=_fields(reform_policy_id=None)
    )

    ((_name, submission),) = simulation.calls
    assert isinstance(submission, HouseholdReportSubmission)
    assert submission.reform is None
    assert report.reform_simulation_id is None


def test_a_household_only_country_has_household_reports() -> None:
    simulation = FakeHouseholdReportSimulation()

    report = household_report_service(simulation).submit_report(
        country_id="zz",
        report_input=_fields(
            reform_policy_id=None, household_id=HOUSEHOLD_ONLY_HOUSEHOLD_ID
        ),
    )

    assert report.country_id == "zz"
    assert [name for name, _argument in simulation.calls] == ["submit_report"]


def test_a_country_without_household_calculations_is_refused_first() -> None:
    simulation = FakeHouseholdReportSimulation()

    with pytest.raises(HouseholdReportsUnsupportedError, match="'xx'"):
        household_report_service(simulation).submit_report(
            country_id="xx", report_input=_fields()
        )

    assert simulation.calls == []


def test_an_unknown_household_is_not_found_before_the_entrypoint() -> None:
    simulation = FakeHouseholdReportSimulation()

    with pytest.raises(HouseholdNotFoundError):
        household_report_service(simulation, households=FakeHouseholds()).submit_report(
            country_id="us", report_input=_fields()
        )

    assert simulation.calls == []


def test_another_countrys_household_is_not_found() -> None:
    simulation = FakeHouseholdReportSimulation()

    with pytest.raises(HouseholdNotFoundError):
        household_report_service(simulation).submit_report(
            country_id="uk", report_input=_fields(reform_policy_id=None)
        )

    assert simulation.calls == []


def test_an_unknown_policy_is_not_found_before_the_entrypoint() -> None:
    simulation = FakeHouseholdReportSimulation()

    with pytest.raises(PolicyNotFoundError):
        household_report_service(simulation).submit_report(
            country_id="us",
            report_input=HouseholdReportFields(
                kind="household",
                household_id=HOUSEHOLD_ID,
                baseline=HouseholdPolicyChoice(policy_id=HOUSEHOLD_ID),
                reform=None,
            ),
        )

    assert simulation.calls == []


def test_a_household_without_a_default_year_is_refused_before_the_entrypoint() -> None:
    simulation = FakeHouseholdReportSimulation()
    households = FakeHouseholds(stored_household(default_year=None))

    with pytest.raises(HouseholdReportYearError):
        household_report_service(simulation, households=households).submit_report(
            country_id="us", report_input=_fields()
        )

    assert simulation.calls == []


def test_the_entrypoint_refusal_reaches_the_caller_unchanged() -> None:
    simulation = FakeHouseholdReportSimulation()
    simulation.error = SimulationRequestRefusedError("gov.x is not in this catalog")

    with pytest.raises(SimulationRequestRefusedError, match=r"gov\.x"):
        household_report_service(simulation).submit_report(
            country_id="us", report_input=_fields()
        )
