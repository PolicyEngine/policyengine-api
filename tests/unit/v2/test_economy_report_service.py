"""The v2 economy report service, with SQLite countries rows and a fake entrypoint."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from policyengine_api.services.v2.economy_reports.types import EconomyReportFields
from policyengine_api.services.v2.economy_reports.validators import (
    EconomyReportNotFoundError,
    EconomyReportsUnsupportedError,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    EconomyReportSubmission,
    ReportStatus,
    RunTrigger,
    SimulationChoice,
    SimulationRequestRefusedError,
)
from tests.unit.v2.economy_report_support import (
    BASELINE_SIMULATION_ID,
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


def test_a_rerun_runs_on_the_current_catalog_with_the_manual_trigger() -> None:
    simulation = FakeEconomyReportSimulation(report_record(run=report_run_record()))

    run = economy_report_service(simulation).run_report(
        country_id="us", report_id=REPORT_ID, force=True
    )

    assert simulation.calls == [
        ("list_report_runs", REPORT_ID),
        ("get_simulation", BASELINE_SIMULATION_ID),
        (
            "run_report",
            {
                "report_id": REPORT_ID,
                "policyengine_version": CURRENT_POLICYENGINE_VERSION,
                "trigger": RunTrigger.MANUAL,
                "force": True,
            },
        ),
    ]
    assert run.trigger == "manual"


def test_a_rerun_in_a_household_only_country_is_refused_before_the_entrypoint() -> None:
    simulation = FakeEconomyReportSimulation(report_record(country_id="zz"))

    with pytest.raises(EconomyReportsUnsupportedError) as raised:
        economy_report_service(simulation).run_report(
            country_id="zz", report_id=REPORT_ID, force=False
        )

    assert "'zz'" in str(raised.value)
    assert simulation.calls == []


@pytest.mark.parametrize(
    "reports",
    [(), (report_record(country_id="uk"),)],
    ids=["unknown", "other-country"],
)
def test_a_rerun_of_a_report_not_in_the_country_is_not_found(reports) -> None:
    simulation = FakeEconomyReportSimulation(*reports)

    with pytest.raises(EconomyReportNotFoundError):
        economy_report_service(simulation).run_report(
            country_id="us", report_id=REPORT_ID, force=False
        )

    assert "run_report" not in [name for name, _ in simulation.calls]


def test_a_rerun_the_entrypoint_refuses_reaches_the_caller() -> None:
    simulation = FakeEconomyReportSimulation(report_record(run=report_run_record()))
    reason = "us has no catalog for PolicyEngine.py 6.7.5"
    simulation.run_error = SimulationRequestRefusedError(reason)

    with pytest.raises(SimulationRequestRefusedError, match=reason):
        economy_report_service(simulation).run_report(
            country_id="us", report_id=REPORT_ID, force=False
        )


def test_a_reports_runs_are_listed_newest_first() -> None:
    simulation = FakeEconomyReportSimulation(report_record())
    service = economy_report_service(simulation)
    service.get_report(country_id="us", report_id=REPORT_ID)
    service.run_report(country_id="us", report_id=REPORT_ID, force=True)

    runs = service.list_report_runs(country_id="us", report_id=REPORT_ID)

    assert [run.trigger for run in runs] == ["manual", "system"]


def test_the_runs_of_a_report_not_in_the_country_are_not_found() -> None:
    simulation = FakeEconomyReportSimulation(report_record(country_id="uk"))

    with pytest.raises(EconomyReportNotFoundError):
        economy_report_service(simulation).list_report_runs(
            country_id="us", report_id=REPORT_ID
        )


def test_listed_reports_keep_the_asked_order_and_only_the_countrys() -> None:
    second_id = UUID("00000000-0000-4000-8000-000000000201")
    other_country_id = UUID("00000000-0000-4000-8000-000000000202")
    unknown_id = UUID("00000000-0000-4000-8000-000000000203")
    simulation = FakeEconomyReportSimulation(
        report_record(),
        report_record(report_id=second_id, run=report_run_record()),
        report_record(report_id=other_country_id, country_id="uk"),
    )

    reports = economy_report_service(simulation).list_reports(
        country_id="us",
        report_ids=[second_id, unknown_id, REPORT_ID, other_country_id, second_id],
    )

    assert [report.id for report in reports] == [second_id, REPORT_ID]
    assert reports[1].status is ReportStatus.NOT_RUN
    assert [name for name, _ in simulation.calls] == ["get_report"] * 4


class SimultaneousFirstReads(FakeEconomyReportSimulation):
    """Hold each of the first two report reads until both have read the report."""

    def __init__(self, *reports) -> None:
        super().__init__(*reports)
        self._first_reads = threading.Barrier(2, timeout=5)
        self._reads_lock = threading.Lock()
        self._reads = 0

    def get_report(self, report_id):
        report = super().get_report(report_id)
        with self._reads_lock:
            self._reads += 1
            first_read = self._reads <= 2
        if first_read:
            self._first_reads.wait()
        return report


def test_simultaneous_first_reads_share_one_system_run() -> None:
    """Both reads see no run and start one; the entrypoint records one run.

    The entrypoint returns a report's newest run to a system run, under a
    lock, so the Public API must start first runs only with the system
    trigger and no force, and answer with the run the entrypoint returns.
    """
    simulation = SimultaneousFirstReads(report_record(legacy_report_id=615))
    service = economy_report_service(simulation)

    with ThreadPoolExecutor(max_workers=2) as executor:
        reads = [
            executor.submit(service.get_report, country_id="us", report_id=REPORT_ID)
            for _ in range(2)
        ]
        reports = [read.result(timeout=10) for read in reads]

    run_starts = [call for name, call in simulation.calls if name == "run_report"]
    assert len(run_starts) == 2
    assert all(
        start["trigger"] is RunTrigger.SYSTEM and start["force"] is False
        for start in run_starts
    )
    assert len(simulation.runs[REPORT_ID]) == 1
    assert {report.run.id for report in reports if report.run is not None} == {
        simulation.runs[REPORT_ID][0].id
    }
    assert all(report.status is ReportStatus.PENDING for report in reports)


def _unreadable_succeeded_report(country_id: str = "us"):
    simulation = FakeEconomyReportSimulation(
        report_record(
            country_id=country_id,
            run=report_run_record(status=ReportStatus.SUCCEEDED),
        )
    )
    simulation.unreadable_results.add(REPORT_ID)
    return simulation


def test_a_report_whose_result_cannot_be_read_back_can_run_again() -> None:
    """Re-running is how such a report becomes readable again."""
    simulation = _unreadable_succeeded_report()

    run = economy_report_service(simulation).run_report(
        country_id="us", report_id=REPORT_ID, force=False
    )

    assert run.trigger == "manual"
    assert "get_report" not in [name for name, _ in simulation.calls]


def test_the_runs_of_a_report_whose_result_cannot_be_read_back_are_listed() -> None:
    simulation = _unreadable_succeeded_report()

    runs = economy_report_service(simulation).list_report_runs(
        country_id="us", report_id=REPORT_ID
    )

    assert [run.status for run in runs] == [ReportStatus.SUCCEEDED]
    assert "get_report" not in [name for name, _ in simulation.calls]


def test_a_report_of_another_country_with_runs_is_not_found() -> None:
    simulation = FakeEconomyReportSimulation(
        report_record(country_id="uk", run=report_run_record())
    )

    with pytest.raises(EconomyReportNotFoundError):
        economy_report_service(simulation).run_report(
            country_id="us", report_id=REPORT_ID, force=True
        )

    assert "run_report" not in [name for name, _ in simulation.calls]


def test_a_listing_leaves_out_a_report_whose_result_cannot_be_read_back() -> None:
    readable_id = UUID("00000000-0000-4000-8000-000000000204")
    simulation = _unreadable_succeeded_report()
    simulation.reports[readable_id] = report_record(report_id=readable_id)

    reports = economy_report_service(simulation).list_reports(
        country_id="us", report_ids=[REPORT_ID, readable_id]
    )

    assert [report.id for report in reports] == [readable_id]
