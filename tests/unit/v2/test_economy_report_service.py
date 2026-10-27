"""The v2 economy report service, with SQLite countries rows and a fake entrypoint."""

from __future__ import annotations

import pytest

from policyengine_api.services.v2.economy_reports.types import (
    EconomyReportFields,
    EconomyReportSubmission,
    SimulationChoice,
    SimulationRequestRefusedError,
)
from policyengine_api.services.v2.economy_reports.validators import (
    EconomyReportsUnsupportedError,
)
from tests.unit.v2.economy_report_support import (
    CURRENT_POLICYENGINE_VERSION,
    REFORM_POLICY_ID,
    FakeEconomyReportSimulation,
    economy_report_service,
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
