"""Saved reports that name v2 household reports, checked with the entrypoint.

A saved report's v2 ID is checked with the Simulation Entrypoint before it is
saved; an ID that is not one of the country's economy reports may be one of
its household reports.
"""

from __future__ import annotations

import pytest

from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.simulation_refs.services import (
    SimulationReferenceService,
)
from policyengine_api.services.v2.simulation_refs.validators import (
    SimulationReferenceNotFoundError,
)
from tests.unit.v2.economy_report_support import (
    REPORT_ID,
    FakeEconomyReportSimulation,
    report_record,
    report_run_record,
)
from tests.unit.v2.household_report_support import (
    HOUSEHOLD_REPORT_ID,
    FakeHouseholdReportSimulation,
    household_report_record,
)


def test_a_household_report_of_the_country_can_be_saved() -> None:
    household_reports = FakeHouseholdReportSimulation(household_report_record())

    SimulationReferenceService(
        FakeEconomyReportSimulation(), household_reports=household_reports
    ).require_report(country_id="us", report_id=HOUSEHOLD_REPORT_ID)

    assert household_reports.calls == [("get_report", HOUSEHOLD_REPORT_ID)]


def test_another_countrys_household_report_cannot_be_saved() -> None:
    household_reports = FakeHouseholdReportSimulation(
        household_report_record(country_id="uk")
    )

    with pytest.raises(SimulationReferenceNotFoundError):
        SimulationReferenceService(
            FakeEconomyReportSimulation(), household_reports=household_reports
        ).require_report(country_id="us", report_id=HOUSEHOLD_REPORT_ID)


def test_a_report_of_neither_kind_cannot_be_saved() -> None:
    with pytest.raises(SimulationReferenceNotFoundError):
        SimulationReferenceService(
            FakeEconomyReportSimulation(),
            household_reports=FakeHouseholdReportSimulation(),
        ).require_report(country_id="us", report_id=HOUSEHOLD_REPORT_ID)


def test_an_economy_report_is_checked_without_asking_for_a_household_report() -> None:
    household_reports = FakeHouseholdReportSimulation()

    SimulationReferenceService(
        FakeEconomyReportSimulation(report_record(run=report_run_record())),
        household_reports=household_reports,
    ).require_report(country_id="us", report_id=REPORT_ID)

    assert household_reports.calls == []


def test_a_household_report_was_not_migrated_from_a_v1_report() -> None:
    household_reports = FakeHouseholdReportSimulation(household_report_record())

    with pytest.raises(AssociationReferenceConflictError, match="was not migrated"):
        SimulationReferenceService(
            FakeEconomyReportSimulation(), household_reports=household_reports
        ).require_report(
            country_id="us", report_id=HOUSEHOLD_REPORT_ID, legacy_report_id=615
        )


def test_an_unavailable_household_check_is_not_taken_for_a_missing_report() -> None:
    household_reports = FakeHouseholdReportSimulation(household_report_record())
    household_reports.error = SimulationServiceUnavailableError("unreachable")

    with pytest.raises(SimulationServiceUnavailableError):
        SimulationReferenceService(
            FakeEconomyReportSimulation(), household_reports=household_reports
        ).require_report(country_id="us", report_id=HOUSEHOLD_REPORT_ID)


def test_the_default_checker_also_checks_household_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from policyengine_api.fastapi_routes import dependencies

    household_reports = FakeHouseholdReportSimulation(household_report_record())
    monkeypatch.setattr(
        dependencies,
        "_default_economy_report_simulation",
        FakeEconomyReportSimulation,
    )
    monkeypatch.setattr(
        dependencies,
        "_default_household_report_simulation",
        lambda: household_reports,
    )

    dependencies._default_simulation_reference_checker().require_report(
        country_id="us", report_id=HOUSEHOLD_REPORT_ID
    )

    assert household_reports.calls == [("get_report", HOUSEHOLD_REPORT_ID)]
