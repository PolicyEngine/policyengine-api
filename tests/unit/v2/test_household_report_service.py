"""The household report service.

It runs with SQLite countries and catalog rows, fake stored households and
policies, and a fake Simulation Entrypoint.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from policyengine_api.services.v2.household_reports.database_session import (
    HouseholdReportDatabaseSession,
)
from policyengine_api.services.v2.household_reports.services import (
    V2HouseholdReportService,
)
from policyengine_api.services.v2.household_reports.types import (
    HouseholdPolicyChoice,
    HouseholdReportFields,
    HouseholdReportSubmission,
)
from policyengine_api.services.v2.household_reports.validators import (
    HouseholdReportNotFoundError,
    HouseholdReportsUnsupportedError,
    HouseholdReportYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ReportStatus,
    RunTrigger,
    SimulationRequestRefusedError,
)
from tests.unit.v2.economy_report_support import CURRENT_POLICYENGINE_VERSION
from tests.unit.v2.household_report_support import (
    HOUSEHOLD_ID,
    HOUSEHOLD_ONLY_HOUSEHOLD_ID,
    HOUSEHOLD_REFORM_POLICY_ID,
    HOUSEHOLD_REPORT_ID,
    OLDER_CATALOG_VERSION_ID,
    OLDER_POLICYENGINE_VERSION,
    UNKNOWN_CATALOG_VERSION_ID,
    FakeHouseholdReportSimulation,
    FakeHouseholds,
    FakePolicies,
    household_report_record,
    household_report_service,
    household_report_store,
    on_catalog_version,
    stored_household,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmodel import Session


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
                add_missing_variables=False,
            ),
        )
    ]
    assert report.status is ReportStatus.PENDING
    assert report.run is not None
    assert report.run.policyengine_version == CURRENT_POLICYENGINE_VERSION


class CountingDatabaseSession(HouseholdReportDatabaseSession):
    """Count the read sessions the service opens."""

    def __init__(self) -> None:
        super().__init__(household_report_store())
        self.reads = 0

    @contextmanager
    def read(self) -> Iterator[Session]:
        self.reads += 1
        with super().read() as session:
            yield session


def _service_on(
    database_session: HouseholdReportDatabaseSession,
    simulation: FakeHouseholdReportSimulation,
) -> V2HouseholdReportService:
    return V2HouseholdReportService(
        database_session,
        households=FakeHouseholds(stored_household()),
        policies=FakePolicies({HOUSEHOLD_REFORM_POLICY_ID: "us"}),
        simulation=simulation,
        current_policyengine_version=CURRENT_POLICYENGINE_VERSION,
    )


def test_a_submission_names_the_version_it_sent_without_reading_the_catalog() -> None:
    """The first run is on the catalog version of the version sent.

    So once the entrypoint has created the report, no database read can fail
    the answer.
    """
    database_session = CountingDatabaseSession()
    simulation = FakeHouseholdReportSimulation()
    simulation.next_catalog_version_id = UNKNOWN_CATALOG_VERSION_ID

    report = _service_on(database_session, simulation).submit_report(
        country_id="us", report_input=_fields()
    )

    assert report.run is not None
    assert report.run.policyengine_version == CURRENT_POLICYENGINE_VERSION
    # Only the countries row, before the entrypoint is asked.
    assert database_session.reads == 1


def test_a_read_run_names_the_policyengine_version_of_its_catalog_version() -> None:
    simulation = FakeHouseholdReportSimulation(
        on_catalog_version(household_report_record(), OLDER_CATALOG_VERSION_ID)
    )

    report = household_report_service(simulation).get_report(
        country_id="us", report_id=HOUSEHOLD_REPORT_ID
    )

    assert report.run is not None
    assert report.run.policyengine_version == OLDER_POLICYENGINE_VERSION


def test_a_read_run_on_a_catalog_version_the_public_api_lacks_names_no_version() -> (
    None
):
    simulation = FakeHouseholdReportSimulation(
        on_catalog_version(household_report_record(), UNKNOWN_CATALOG_VERSION_ID)
    )

    report = household_report_service(simulation).get_report(
        country_id="us", report_id=HOUSEHOLD_REPORT_ID
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


def test_a_report_is_read_with_its_runs_policyengine_version() -> None:
    simulation = FakeHouseholdReportSimulation(
        household_report_record(status=ReportStatus.SUCCEEDED)
    )

    report = household_report_service(simulation).get_report(
        country_id="us", report_id=HOUSEHOLD_REPORT_ID
    )

    assert report.status is ReportStatus.SUCCEEDED
    assert report.run is not None
    assert report.run.policyengine_version == CURRENT_POLICYENGINE_VERSION
    assert simulation.calls == [("get_report", HOUSEHOLD_REPORT_ID)]


def test_a_report_before_its_first_run_is_read_without_a_catalog_read() -> None:
    simulation = FakeHouseholdReportSimulation(household_report_record(status=None))

    report = household_report_service(simulation).get_report(
        country_id="us", report_id=HOUSEHOLD_REPORT_ID
    )

    assert report.status is ReportStatus.NOT_RUN
    assert report.run is None


@pytest.mark.parametrize(
    "reports",
    [(), (household_report_record(country_id="uk"),)],
    ids=["unknown", "other-country"],
)
def test_a_report_the_country_lacks_is_not_found(reports) -> None:
    simulation = FakeHouseholdReportSimulation(*reports)

    with pytest.raises(HouseholdReportNotFoundError):
        household_report_service(simulation).get_report(
            country_id="us", report_id=HOUSEHOLD_REPORT_ID
        )


def test_reports_are_listed_in_the_order_asked_once_each() -> None:
    second_report_id = UUID("00000000-0000-4000-8000-0000000003a1")
    other_country_report_id = UUID("00000000-0000-4000-8000-0000000003a2")
    unknown_report_id = UUID("00000000-0000-4000-8000-0000000003a3")
    simulation = FakeHouseholdReportSimulation(
        household_report_record(),
        household_report_record(report_id=second_report_id, status=None),
        household_report_record(report_id=other_country_report_id, country_id="uk"),
    )

    reports = household_report_service(simulation).list_reports(
        country_id="us",
        report_ids=[
            second_report_id,
            unknown_report_id,
            HOUSEHOLD_REPORT_ID,
            other_country_report_id,
            second_report_id,
        ],
    )

    assert [report.id for report in reports] == [second_report_id, HOUSEHOLD_REPORT_ID]
    assert reports[1].run is not None
    assert reports[1].run.policyengine_version == CURRENT_POLICYENGINE_VERSION


@pytest.mark.parametrize("force", [False, True])
def test_a_rerun_runs_on_the_current_version_and_answers_the_new_run(
    *, force: bool
) -> None:
    simulation = FakeHouseholdReportSimulation(
        household_report_record(status=ReportStatus.SUCCEEDED)
    )
    database_session = CountingDatabaseSession()

    run = _service_on(database_session, simulation).run_report(
        country_id="us", report_id=HOUSEHOLD_REPORT_ID, force=force
    )

    assert simulation.calls == [
        ("get_report", HOUSEHOLD_REPORT_ID),
        (
            "run_report",
            {
                "report_id": HOUSEHOLD_REPORT_ID,
                "policyengine_version": CURRENT_POLICYENGINE_VERSION,
                "trigger": RunTrigger.MANUAL,
                "force": force,
            },
        ),
    ]
    assert run.trigger == "manual"
    assert run.status is ReportStatus.PENDING
    assert run.policyengine_version == CURRENT_POLICYENGINE_VERSION
    # Only the countries row, before the entrypoint is asked to run it.
    assert database_session.reads == 1


@pytest.mark.parametrize(
    "reports",
    [(), (household_report_record(country_id="uk"),)],
    ids=["unknown", "other-country"],
)
def test_a_rerun_of_a_report_the_country_lacks_is_not_found(reports) -> None:
    simulation = FakeHouseholdReportSimulation(*reports)

    with pytest.raises(HouseholdReportNotFoundError):
        household_report_service(simulation).run_report(
            country_id="us", report_id=HOUSEHOLD_REPORT_ID, force=False
        )

    assert [name for name, _argument in simulation.calls] == ["get_report"]


def test_a_rerun_in_a_country_without_household_calculations_is_refused_first() -> None:
    simulation = FakeHouseholdReportSimulation(household_report_record(country_id="xx"))

    with pytest.raises(HouseholdReportsUnsupportedError, match="'xx'"):
        household_report_service(simulation).run_report(
            country_id="xx", report_id=HOUSEHOLD_REPORT_ID, force=False
        )

    assert simulation.calls == []


def test_a_report_can_ask_for_every_variable_the_household_lacks() -> None:
    simulation = FakeHouseholdReportSimulation()

    household_report_service(simulation).submit_report(
        country_id="us",
        report_input=HouseholdReportFields(
            kind="household",
            household_id=HOUSEHOLD_ID,
            baseline=HouseholdPolicyChoice(),
            reform=None,
            add_missing_variables=True,
        ),
    )

    ((_name, submission),) = simulation.calls
    assert isinstance(submission, HouseholdReportSubmission)
    assert submission.add_missing_variables is True
