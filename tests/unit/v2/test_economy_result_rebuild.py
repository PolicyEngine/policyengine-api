"""Rebuild report runs' economy results from the rows the simulation service stores.

Each result is stored through a port of the simulation service's writer
(``tests.fixtures.economy_results``), so a rebuild that matches the result
reverses that writer.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from policyengine_api.data.v2.models import (
    BudgetSummary,
    CongressionalDistrictImpact,
    ConstituencyImpact,
    DecileImpact,
    Inequality,
    IntraDecileImpact,
    LaborSupplyDecileResponse,
    LaborSupplyResponse,
    LocalAuthorityImpact,
    Poverty,
    ProgramStatistics,
)
from policyengine_api.services.v2.stored_reports.economy_results import (
    transformations as result_transformations,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultRows,
    EconomyResultUnreadableError,
    ReportRunResultColumns,
)
from tests.fixtures.economy_results import (
    RunIds,
    economy_result_rows,
    uk_economy_result,
    us_economy_result,
)

TABLE_MODELS = {
    "budget_summary": BudgetSummary,
    "program_statistics": ProgramStatistics,
    "decile_impacts": DecileImpact,
    "intra_decile_impacts": IntraDecileImpact,
    "poverty": Poverty,
    "inequality": Inequality,
    "labor_supply_responses": LaborSupplyResponse,
    "labor_supply_decile_responses": LaborSupplyDecileResponse,
    "congressional_district_impacts": CongressionalDistrictImpact,
    "constituency_impacts": ConstituencyImpact,
    "local_authority_impacts": LocalAuthorityImpact,
}


def stored_rows(
    output: dict[str, Any], *, country: str, reverse_rows: bool = False
) -> EconomyResultRows:
    """Store ``output`` as the writer does and load its rows as table models.

    With ``reverse_rows``, each table's rows come back in reverse order, as a
    query without an order may return them.
    """
    run_ids = RunIds(
        report_run_id=uuid4(),
        baseline_simulation_run_id=uuid4(),
        reform_simulation_run_id=uuid4(),
    )
    stored = economy_result_rows(output, run_ids=run_ids, country=country)
    tables: dict[str, tuple[Any, ...]] = {}
    for table, rows in stored.rows.items():
        loaded = [TABLE_MODELS[table](id=uuid4(), **row) for row in rows]
        if reverse_rows:
            loaded.reverse()
        tables[table] = tuple(loaded)
    return EconomyResultRows(
        country_id=country,
        report_run=ReportRunResultColumns(
            country_package_version=output["model_version"],
            **stored.report_run_columns,
        ),
        baseline_simulation_run_id=run_ids.baseline_simulation_run_id,
        reform_simulation_run_id=run_ids.reform_simulation_run_id,
        **tables,
    )


def as_json(value: Any) -> Any:
    """Return ``value`` as the simulation service serves it: through JSON."""
    return json.loads(json.dumps(value))


@pytest.mark.parametrize(
    ("country", "output"),
    [
        ("us", us_economy_result()),
        ("uk", uk_economy_result()),
    ],
    ids=["us", "uk"],
)
def test_result_rows_rebuild_the_result_the_simulation_service_stored(
    country: str, output: dict[str, Any]
) -> None:
    rebuilt = result_transformations.economy_result(
        stored_rows(output, country=country)
    )

    assert rebuilt.model_dump(mode="json") == as_json(output)


@pytest.mark.parametrize(
    ("country", "output"),
    [
        ("us", us_economy_result()),
        ("uk", uk_economy_result()),
    ],
    ids=["us", "uk"],
)
def test_result_rows_in_any_order_rebuild_the_same_result(
    country: str, output: dict[str, Any]
) -> None:
    rebuilt = result_transformations.economy_result(
        stored_rows(output, country=country, reverse_rows=True)
    )

    assert rebuilt.model_dump(mode="json") == as_json(output)


def test_rebuilt_result_lists_its_parts_in_the_simulation_service_order() -> None:
    rebuilt = result_transformations.economy_result(
        stored_rows(us_economy_result(), country="us")
    )

    assert list(rebuilt.model_dump(mode="json")) == list(us_economy_result())


def test_relative_decile_changes_are_fractions_of_the_stored_percentages() -> None:
    output = us_economy_result()
    output["decile"]["relative"]["3"] = 0.07
    rebuilt = result_transformations.economy_result(stored_rows(output, country="us"))

    assert rebuilt.decile.relative["3"] == pytest.approx(0.07)


def test_a_uk_result_without_a_state_income_tax_row_reports_none_collected() -> None:
    rows = stored_rows(uk_economy_result(), country="uk")

    assert "household_state_income_tax" not in {
        row.variable_name for row in rows.budget_summary
    }
    assert (
        result_transformations.economy_result(rows).budget.state_tax_revenue_impact
        == 0.0
    )


def test_an_intra_decile_breakdown_without_rows_has_empty_categories() -> None:
    rows = stored_rows(us_economy_result(), country="us")
    rows = replace(
        rows,
        intra_decile_impacts=tuple(
            row for row in rows.intra_decile_impacts if row.decile_type != "income"
        ),
    )

    intra_decile = result_transformations.economy_result(rows).intra_decile

    assert set(intra_decile.deciles) == {
        "Lose more than 5%",
        "Lose less than 5%",
        "No change",
        "Gain less than 5%",
        "Gain more than 5%",
    }
    assert all(values == [] for values in intra_decile.deciles.values())
    assert all(share == 0.0 for share in intra_decile.all.values())


def _without(rows: EconomyResultRows, table: str, keep: Any) -> EconomyResultRows:
    return replace(
        rows, **{table: tuple(row for row in getattr(rows, table) if keep(row))}
    )


@pytest.mark.parametrize(
    ("table", "keep", "missing"),
    [
        (
            "budget_summary",
            lambda row: row.variable_name != "household_tax",
            "household_tax",
        ),
        (
            "budget_summary",
            lambda row: row.variable_name != "household_state_income_tax",
            "household_state_income_tax",
        ),
        (
            "poverty",
            lambda row: (
                not (row.poverty_type == "spm_deep" and row.filter_group == "senior")
            ),
            "spm_deep",
        ),
        ("inequality", lambda row: False, "inequality"),
        ("decile_impacts", lambda row: row.decile_variable is not None, "decile"),
    ],
    ids=[
        "tax",
        "us-state-income-tax",
        "deep-poverty-of-seniors",
        "inequality",
        "income-deciles",
    ],
)
def test_a_result_without_a_part_every_result_has_is_unreadable(
    table: str, keep: Any, missing: str
) -> None:
    rows = _without(
        stored_rows(us_economy_result(), country="us"),
        table,
        keep,
    )

    with pytest.raises(EconomyResultUnreadableError, match=missing):
        result_transformations.economy_result(rows)


def test_a_result_without_its_data_version_is_unreadable() -> None:
    rows = stored_rows(us_economy_result(), country="us")
    rows = replace(rows, report_run=replace(rows.report_run, data_version=None))

    with pytest.raises(EconomyResultUnreadableError, match="data version"):
        result_transformations.economy_result(rows)


def test_a_null_stored_figure_makes_the_result_unreadable() -> None:
    rows = stored_rows(us_economy_result(), country="us")
    inequality = rows.inequality[0]
    inequality.gini = None

    with pytest.raises(EconomyResultUnreadableError, match="gini"):
        result_transformations.economy_result(rows)


def test_a_district_of_an_unknown_state_makes_the_result_unreadable() -> None:
    rows = stored_rows(us_economy_result(), country="us")
    district = rows.congressional_district_impacts[0]
    district.state_fips = 3

    with pytest.raises(EconomyResultUnreadableError, match="FIPS"):
        result_transformations.economy_result(rows)


def test_a_country_without_poverty_measures_is_unreadable() -> None:
    rows = replace(
        stored_rows(us_economy_result(), country="us"),
        country_id="ca",
    )

    with pytest.raises(EconomyResultUnreadableError, match="'ca'"):
        result_transformations.economy_result(rows)
