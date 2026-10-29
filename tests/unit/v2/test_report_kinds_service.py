"""Which kind's service answers each /v2/reports operation."""

from __future__ import annotations

from uuid import UUID

import pytest

from policyengine_api.services.v2.report_kinds.services import V2ReportService
from policyengine_api.services.v2.report_kinds.validators import ReportNotFoundError
from policyengine_api.services.v2.simulation_entrypoint.types import (
    SimulationServiceUnavailableError,
)
from tests.unit.v2.economy_report_support import (
    REPORT_ID,
    FakeEconomyReportSimulation,
    economy_report_service,
    report_record,
    report_run_record,
)
from tests.unit.v2.household_report_support import (
    HOUSEHOLD_REPORT_ID,
    FakeHouseholdReportSimulation,
    household_report_record,
    household_report_service,
    household_report_store,
)

UNKNOWN_REPORT_ID = UUID("00000000-0000-4000-8000-0000000004ff")


def _service(
    economy_simulation: FakeEconomyReportSimulation,
    household_simulation: FakeHouseholdReportSimulation,
) -> V2ReportService:
    sessions = household_report_store()
    return V2ReportService(
        economy_reports=lambda: economy_report_service(economy_simulation, sessions),
        household_reports=lambda: household_report_service(
            household_simulation, sessions=sessions
        ),
    )


def test_an_economy_report_is_read_without_asking_for_a_household_report() -> None:
    economy_simulation = FakeEconomyReportSimulation(
        report_record(run=report_run_record())
    )
    household_simulation = FakeHouseholdReportSimulation()

    report = _service(economy_simulation, household_simulation).get_report(
        country_id="us", report_id=REPORT_ID
    )

    assert report.id == REPORT_ID
    assert household_simulation.calls == []


def test_a_household_report_is_read_once_no_economy_report_has_its_id() -> None:
    economy_simulation = FakeEconomyReportSimulation()
    household_simulation = FakeHouseholdReportSimulation(household_report_record())

    report = _service(economy_simulation, household_simulation).get_report(
        country_id="us", report_id=HOUSEHOLD_REPORT_ID
    )

    assert report.id == HOUSEHOLD_REPORT_ID
    assert [name for name, _argument in economy_simulation.calls] == ["get_report"]
    assert household_simulation.calls == [("get_report", HOUSEHOLD_REPORT_ID)]


def test_a_report_of_neither_kind_is_not_found() -> None:
    service = _service(FakeEconomyReportSimulation(), FakeHouseholdReportSimulation())

    with pytest.raises(ReportNotFoundError, match="was not found in country 'us'"):
        service.get_report(country_id="us", report_id=UNKNOWN_REPORT_ID)


def test_an_unavailable_economy_read_is_not_taken_for_a_missing_report() -> None:
    economy_simulation = FakeEconomyReportSimulation()
    economy_simulation.error = SimulationServiceUnavailableError("unreachable")
    household_simulation = FakeHouseholdReportSimulation(household_report_record())

    with pytest.raises(SimulationServiceUnavailableError):
        _service(economy_simulation, household_simulation).get_report(
            country_id="us", report_id=HOUSEHOLD_REPORT_ID
        )

    assert household_simulation.calls == []


def test_a_listing_holds_both_kinds_in_the_order_asked() -> None:
    economy_simulation = FakeEconomyReportSimulation(
        report_record(run=report_run_record())
    )
    household_simulation = FakeHouseholdReportSimulation(household_report_record())

    reports = _service(economy_simulation, household_simulation).list_reports(
        country_id="us",
        report_ids=[HOUSEHOLD_REPORT_ID, UNKNOWN_REPORT_ID, REPORT_ID],
    )

    assert [report.id for report in reports] == [HOUSEHOLD_REPORT_ID, REPORT_ID]
    assert [argument for name, argument in household_simulation.calls] == [
        HOUSEHOLD_REPORT_ID,
        UNKNOWN_REPORT_ID,
    ]
