"""Builders of budget-window report reads for the v2 report route tests."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from policyengine_api.services.v2.stored_reports.budget_window_results.types import (
    BudgetWindowResult,
)
from policyengine_api.services.v2.stored_reports.types import (
    BudgetWindowReportRead,
    BudgetWindowReportSummaryRead,
    BudgetWindowRunRead,
    BudgetWindowYearRead,
    ReportSimulationRead,
)
from tests.unit.v2.stored_report_support import (
    BASELINE_SIMULATION_ID,
    CREATED_AT,
    CURRENT_VERSIONS,
    POLICY_ID,
    REFORM_SIMULATION_ID,
)

BUDGET_WINDOW_REPORT_ID = UUID("00000000-0000-0000-0000-00000000a101")
BUDGET_WINDOW_RUN_ID = UUID("00000000-0000-0000-0000-00000000a102")
YEAR_RUN_IDS = {
    2026: UUID("00000000-0000-0000-0000-00000000a103"),
    2027: UUID("00000000-0000-0000-0000-00000000a104"),
}
BUDGET_WINDOW_RESULT = {
    "kind": "budgetWindow",
    "startYear": "2026",
    "endYear": "2027",
    "windowSize": 2,
    "annualImpacts": [
        {
            "spm_provenance": None,
            "year": str(year),
            "taxRevenueImpact": tax,
            "federalTaxRevenueImpact": tax - 100.0,
            "stateTaxRevenueImpact": 100.0,
            "benefitSpendingImpact": -50.0,
            "budgetaryImpact": tax + 50.0,
        }
        for year, tax in ((2026, 1000.0), (2027, 1200.0))
    ],
    "totals": {
        "year": "Total",
        "taxRevenueImpact": 2200.0,
        "federalTaxRevenueImpact": 2000.0,
        "stateTaxRevenueImpact": 200.0,
        "benefitSpendingImpact": -100.0,
        "budgetaryImpact": 2300.0,
    },
}


def budget_window_year_read(year: int, **changes: Any) -> BudgetWindowYearRead:
    values: dict[str, Any] = {
        "year": year,
        "id": YEAR_RUN_IDS[year],
        "status": "succeeded",
        "trigger": "initial",
        "country_package_version": "1.4.0",
        "policyengine_version": "4.1.0",
        "baseline_simulation_run_id": UUID(int=year * 2),
        "reform_simulation_run_id": UUID(int=year * 2 + 1),
        "error_message": None,
        "created_at": CREATED_AT,
        "started_at": CREATED_AT,
        "completed_at": CREATED_AT,
    }
    return BudgetWindowYearRead(**{**values, **changes})


def budget_window_run_read(**changes: Any) -> BudgetWindowRunRead:
    values: dict[str, Any] = {
        "id": BUDGET_WINDOW_RUN_ID,
        "status": "succeeded",
        "trigger": "initial",
        "recalculate": False,
        "country_package_version": "1.4.0",
        "policyengine_version": "4.1.0",
        "error_message": None,
        "created_at": CREATED_AT,
        "started_at": CREATED_AT,
        "completed_at": CREATED_AT,
        "years": tuple(budget_window_year_read(year) for year in YEAR_RUN_IDS),
    }
    return BudgetWindowRunRead(**{**values, **changes})


def budget_window_summary_fields(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": BUDGET_WINDOW_REPORT_ID,
        "country_id": "us",
        "kind": "budget_window",
        "label": "Expanded child tax credit, 2026 to 2027",
        "description": None,
        "year": 2026,
        "budget_window_size": 2,
        "region_code": "us",
        "dataset_name": None,
        "baseline_simulation": ReportSimulationRead(
            id=BASELINE_SIMULATION_ID, policy_id=None, dynamic_id=None
        ),
        "reform_simulation": ReportSimulationRead(
            id=REFORM_SIMULATION_ID, policy_id=POLICY_ID, dynamic_id=None
        ),
        "options": {},
        "created_at": CREATED_AT,
        "status": "succeeded",
        "run": budget_window_run_read(),
        "current_versions": CURRENT_VERSIONS,
    }
    return {**values, **changes}


def budget_window_summary_read(**changes: Any) -> BudgetWindowReportSummaryRead:
    return BudgetWindowReportSummaryRead(**budget_window_summary_fields(**changes))


def budget_window_report_read(**changes: Any) -> BudgetWindowReportRead:
    fields = {
        "result": BudgetWindowResult.model_validate(BUDGET_WINDOW_RESULT),
        **budget_window_summary_fields(),
        **changes,
    }
    return BudgetWindowReportRead(**fields)
