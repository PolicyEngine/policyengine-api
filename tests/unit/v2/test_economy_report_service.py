"""The v2 economy report service, with SQLite countries rows and a fake entrypoint."""

from __future__ import annotations

import pytest

from policyengine_api.services.v2.economy_reports.types import (
    EconomyReportFields,
    EconomyReportSubmission,
    ReportStatus,
    RunTrigger,
    SimulationChoice,
    SimulationRequestRefusedError,
)
from policyengine_api.services.v2.economy_reports.validators import (
    EconomyReportNotFoundError,
    EconomyReportsUnsupportedError,
)
from tests.unit.v2.economy_report_support import (
    CURRENT_POLICYENGINE_VERSION,
    REFORM_POLICY_ID,
    REPORT_ID,
    FakeEconomyReportSimulation,
    economy_report_service,
    report_record,
    report_run_record,
)


def _report_fields(**changes) -> EconomyReportFields:
    return EconomyReportFields(
        **{
            "kind": "economy",
            "year": 2026,
            "region_code": "state/ca",
            "baseline": SimulationChoice(),
            "reform": SimulationChoice(policy_id=REFORM_POLICY_ID),
            **changes,
        }
    )


def test_submit_asks_the_entrypoint_for_the_report_on_the_current_catalog() -> None:
    simulation = FakeEconomyReportSimulation()
    service = economy_report_service(simulation)

    report = service.submit_report(
        country_id="us",
        report_input=_report_fields(dataset_name="populace_us_2024"),
    )

    assert simulation.calls == [
        (
            "submit_report",
            EconomyReportSubmission(
                country_id="us",
                policyengine_version=CURRENT_POLICYENGINE_VERSION,
                year=2026,
                region_code="state/ca",
                dataset_name="populace_us_2024",
                baseline=SimulationChoice(),
                reform=SimulationChoice(policy_id=REFORM_POLICY_ID),
            ),
        )
    ]
    assert report == simulation.reports[report.id]


def test_a_household_only_country_is_refused_before_the_entrypoint_is_asked() -> None:
    simulation = FakeEconomyReportSimulation()
    service = economy_report_service(simulation)

    with pytest.raises(EconomyReportsUnsupportedError) as raised:
        service.submit_report(country_id="zz", report_input=_report_fields())

    assert "'zz'" in str(raised.value)
    assert simulation.calls == []


def test_a_country_without_a_countries_row_is_refused() -> None:
    simulation = FakeEconomyReportSimulation()
    service = economy_report_service(simulation)

    with pytest.raises(EconomyReportsUnsupportedError) as raised:
        service.submit_report(country_id="xx", report_input=_report_fields())

    assert "'xx'" in str(raised.value)
    assert simulation.calls == []


def test_the_entrypoint_refusal_reaches_the_caller_unchanged() -> None:
    simulation = FakeEconomyReportSimulation()
    reason = "region place/ca-los_angeles has no household filter"
    simulation.error = SimulationRequestRefusedError(reason)
    service = economy_report_service(simulation)

    with pytest.raises(SimulationRequestRefusedError, match=reason):
        service.submit_report(country_id="us", report_input=_report_fields())


def test_a_report_of_the_country_is_read_as_the_entrypoint_has_it() -> None:
    succeeded = report_record(run=report_run_record(status=ReportStatus.SUCCEEDED))
    simulation = FakeEconomyReportSimulation(succeeded)

    report = economy_report_service(simulation).get_report(
        country_id="us", report_id=REPORT_ID
    )

    assert report == succeeded
    assert simulation.calls == [("get_report", REPORT_ID)]


@pytest.mark.parametrize(
    "reports",
    [(), (report_record(country_id="uk"),)],
    ids=["unknown", "other-country"],
)
def test_a_report_not_in_the_country_is_not_found(reports) -> None:
    simulation = FakeEconomyReportSimulation(*reports)

    with pytest.raises(EconomyReportNotFoundError) as raised:
        economy_report_service(simulation).get_report(
            country_id="us", report_id=REPORT_ID
        )

    assert str(raised.value) == (
        f"Economy report {REPORT_ID} was not found in country 'us'"
    )
    assert [name for name, _ in simulation.calls] == ["get_report"]


def test_reading_a_report_with_no_run_starts_its_first_run() -> None:
    simulation = FakeEconomyReportSimulation(report_record(legacy_report_id=615))

    report = economy_report_service(simulation).get_report(
        country_id="us", report_id=REPORT_ID
    )

    assert simulation.calls[1] == (
        "run_report",
        {
            "report_id": REPORT_ID,
            "policyengine_version": CURRENT_POLICYENGINE_VERSION,
            "trigger": RunTrigger.SYSTEM,
            "force": False,
        },
    )
    assert [name for name, _ in simulation.calls] == [
        "get_report",
        "run_report",
        "get_report",
    ]
    assert report.status is ReportStatus.PENDING
    assert report.run is not None
    assert report.run.trigger == "system"


def test_a_report_with_a_run_is_not_run_again_when_read() -> None:
    simulation = FakeEconomyReportSimulation(report_record(run=report_run_record()))

    economy_report_service(simulation).get_report(country_id="us", report_id=REPORT_ID)

    assert [name for name, _ in simulation.calls] == ["get_report"]


def test_a_household_only_country_report_is_not_run_when_read() -> None:
    simulation = FakeEconomyReportSimulation(report_record(country_id="zz"))

    report = economy_report_service(simulation).get_report(
        country_id="zz", report_id=REPORT_ID
    )

    assert report.status is ReportStatus.NOT_RUN
    assert [name for name, _ in simulation.calls] == ["get_report"]


def test_a_first_run_the_entrypoint_refuses_leaves_the_report_not_run() -> None:
    simulation = FakeEconomyReportSimulation(report_record())
    simulation.run_error = SimulationRequestRefusedError(
        "region constituency/E14000530 is not in the catalog version"
    )

    report = economy_report_service(simulation).get_report(
        country_id="us", report_id=REPORT_ID
    )

    assert report.status is ReportStatus.NOT_RUN
    assert report.run is None


def test_a_migrated_report_is_found_by_its_v1_number_and_first_run() -> None:
    simulation = FakeEconomyReportSimulation(report_record(legacy_report_id=615))

    report = economy_report_service(simulation).get_report_by_legacy_number(
        country_id="us", legacy_report_id=615
    )

    assert report.legacy_report_id == 615
    assert report.run is not None
    assert report.run.trigger == "system"
    assert simulation.calls[0] == ("get_report_by_legacy_id", 615)


def test_an_unknown_v1_number_is_not_found() -> None:
    simulation = FakeEconomyReportSimulation(report_record(legacy_report_id=615))

    with pytest.raises(EconomyReportNotFoundError) as raised:
        economy_report_service(simulation).get_report_by_legacy_number(
            country_id="us", legacy_report_id=616
        )

    assert str(raised.value) == (
        "Economy report migrated from v1 report 616 was not found in country 'us'"
    )
