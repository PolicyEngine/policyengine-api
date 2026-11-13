"""Structural tests for simulation runs, report runs, household jobs and results.

A simulation defines what to calculate and each calculation of it is a run that
records the catalog and PolicyEngine.py versions it used. A report run names
its baseline and reform simulation runs, results are keyed by run, and a
household job calculates one household for one year under one policy.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from policyengine_api.data.v2.models import (
    V2_METADATA,
    BudgetWindowRun,
    LaborSupplyDecileResponse,
    LaborSupplyResponse,
    ReportRun,
    SimulationRun,
)

RUN_STATUSES = ["pending", "running", "succeeded", "failed"]
# The baseline's and reform's cliff gap and share, stored together or not at all.
CLIFF_IMPACT_COLUMNS = (
    "baseline_cliff_gap",
    "baseline_cliff_share",
    "reform_cliff_gap",
    "reform_cliff_share",
)
LABOR_SUPPLY_RESPONSE_COLUMNS = (
    "income_effect_earnings_change",
    "substitution_effect_earnings_change",
    "total_earnings_change",
    "revenue_change",
    "relative_income_effect",
    "relative_substitution_effect",
    "baseline_weekly_hours",
    "reform_weekly_hours",
    "weekly_hours_change",
    "weekly_hours_income_effect",
    "weekly_hours_substitution_effect",
)
LABOR_SUPPLY_DECILE_COLUMNS = (
    "average_income_effect",
    "average_substitution_effect",
    "relative_income_effect",
    "relative_substitution_effect",
)
PER_SIMULATION_RESULT_TABLES = ("inequality", "poverty")
COMPARISON_RESULT_TABLES = (
    "budget_summary",
    "congressional_district_impacts",
    "constituency_impacts",
    "decile_impacts",
    "intra_decile_impacts",
    "local_authority_impacts",
    "program_statistics",
    "withheld_area_codes",
)
# The tables the simulation service and its Modal workers write. The Public API
# writes every other table.
SIMULATION_SIDE_TABLES = frozenset(
    {
        "simulations",
        "simulation_runs",
        "reports",
        "report_runs",
        "budget_window_runs",
        "labor_supply_responses",
        "labor_supply_decile_responses",
        "household_jobs",
        "aggregates",
        "change_aggregates",
        *PER_SIMULATION_RESULT_TABLES,
        *COMPARISON_RESULT_TABLES,
    }
)
# The foreign keys from the simulation service's tables to the Public API's rows,
# with their delete rules. Each service writes only its own tables, and
# PostgreSQL checks every row named on insert.
PUBLIC_API_FOREIGN_KEYS = {
    ("simulations", "dataset_id"): ("datasets", "RESTRICT"),
    ("simulations", "household_id"): ("households", "RESTRICT"),
    ("simulations", "policy_id"): ("policies", "SET NULL"),
    ("simulations", "dynamic_id"): ("dynamics", "SET NULL"),
    ("simulations", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("simulations", "region_id"): ("regions", "SET NULL"),
    ("reports", "user_id"): ("users", "SET NULL"),
    ("reports", "tax_benefit_model_id"): ("tax_benefit_models", "RESTRICT"),
    ("reports", "policy_id"): ("policies", "SET NULL"),
    ("reports", "household_id"): ("households", "RESTRICT"),
    ("reports", "dataset_id"): ("datasets", "SET NULL"),
    ("reports", "region_id"): ("regions", "SET NULL"),
    ("simulation_runs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("simulation_runs", "dataset_id"): ("datasets", "RESTRICT"),
    ("simulation_runs", "region_id"): ("regions", "SET NULL"),
    ("household_jobs", "household_id"): ("households", "RESTRICT"),
    ("household_jobs", "policy_id"): ("policies", "SET NULL"),
    ("household_jobs", "dynamic_id"): ("dynamics", "SET NULL"),
    ("household_jobs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("budget_window_runs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
}


def _foreign_key(table: sa.Table, column_name: str) -> sa.ForeignKey:
    (foreign_key,) = table.c[column_name].foreign_keys
    return foreign_key


def _check_names(table: sa.Table) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }


def _unique_column_sets(table: sa.Table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }


def _indexes(table: sa.Table) -> dict[str, tuple[str, ...]]:
    return {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    }


def test_simulations_keep_only_what_to_calculate() -> None:
    simulations = V2_METADATA.tables["simulations"]

    assert {
        "status",
        "error_message",
        "started_at",
        "completed_at",
        "household_result",
        "output_dataset_id",
    }.isdisjoint(simulations.c.keys())
    assert {
        "simulation_type",
        "dataset_id",
        "household_id",
        "policy_id",
        "dynamic_id",
        "tax_benefit_model_version_id",
        "region_id",
        "filter_field",
        "filter_value",
        "filter_strategy",
        "year",
    } <= set(simulations.c.keys())
    assert "ix_simulations_status_created_at" not in _indexes(simulations)


def test_each_simulation_run_records_its_versions_status_and_output() -> None:
    simulation_runs = V2_METADATA.tables["simulation_runs"]

    required = {
        "simulation_id",
        "year",
        "tax_benefit_model_version_id",
        "country_package_version",
        "policyengine_version",
        "status",
        "forced",
        "created_at",
        "updated_at",
    }
    optional = {
        "dataset_id",
        "region_id",
        "modal_call_id",
        "error_message",
        "started_at",
        "completed_at",
        "household_result",
        "output_uri",
        "output_sha256",
    }
    assert set(simulation_runs.c.keys()) == {"id"} | required | optional
    assert all(not simulation_runs.c[name].nullable for name in required)
    assert all(simulation_runs.c[name].nullable for name in optional)
    assert simulation_runs.c.status.type.name == "v2_simulation_status"
    assert list(simulation_runs.c.status.type.enums) == RUN_STATUSES
    assert simulation_runs.c.modal_call_id.type.length == 255
    assert simulation_runs.c.output_uri.type.length == 2048
    assert simulation_runs.c.output_sha256.type.length == 64
    assert simulation_runs.c.country_package_version.type.length == 128
    assert simulation_runs.c.policyengine_version.type.length == 128

    simulation_key = _foreign_key(simulation_runs, "simulation_id")
    assert simulation_key.target_fullname == "simulations.id"
    assert simulation_key.ondelete == "CASCADE"
    assert {key.target_fullname for key in simulation_runs.foreign_keys} == {
        "simulations.id",
        "tax_benefit_model_versions.id",
        "datasets.id",
        "regions.id",
    }
    assert "ck_simulation_runs_year" in _check_names(simulation_runs)
    assert SimulationRun.__module__.endswith(".simulations")


def test_run_tables_require_a_completion_time_and_index_running_runs() -> None:
    simulation_runs = V2_METADATA.tables["simulation_runs"]
    report_runs = V2_METADATA.tables["report_runs"]
    household_jobs = V2_METADATA.tables["household_jobs"]

    assert {
        "ck_simulation_runs_terminal_completion",
        "ck_simulation_runs_output_pair",
        "ck_simulation_runs_output_sha256_length",
    } <= _check_names(simulation_runs)
    assert "ck_household_jobs_terminal_completion" in _check_names(household_jobs)
    # A simulation has a run per year, so its newest successful run is found
    # per year.
    assert _indexes(simulation_runs) == {
        "ix_simulation_runs_current_output": (
            "simulation_id",
            "year",
            "status",
            "country_package_version",
            "policyengine_version",
            "completed_at",
            "id",
        ),
        "ix_simulation_runs_status_started_at": ("status", "started_at"),
        "ix_simulation_runs_tax_benefit_model_version_id": (
            "tax_benefit_model_version_id",
        ),
        # One unfailed, unforced run per year and version set
        # (test_shared_report_models.py).
        "uq_simulation_runs_unfailed_unforced_versions": (
            "simulation_id",
            "year",
            "tax_benefit_model_version_id",
            "country_package_version",
            "policyengine_version",
        ),
    }
    assert _indexes(report_runs)["ix_report_runs_status_started_at"] == (
        "status",
        "started_at",
    )


def test_report_runs_record_their_modal_call() -> None:
    report_runs = V2_METADATA.tables["report_runs"]

    assert report_runs.c.modal_call_id.nullable
    assert report_runs.c.modal_call_id.type.length == 255
    assert "report_run_comparisons" not in V2_METADATA.tables


def test_report_runs_record_cliff_impact_spm_receipt_and_data_version() -> None:
    """The comparison parts with no result table are typed, except the receipt."""
    report_runs = V2_METADATA.tables["report_runs"]

    for column_name in CLIFF_IMPACT_COLUMNS:
        assert report_runs.c[column_name].nullable, column_name
        assert isinstance(report_runs.c[column_name].type, sa.Float), column_name
    assert "ck_report_runs_cliff_impact_complete" in _check_names(report_runs)
    assert report_runs.c.spm_provenance.nullable
    spm_type = report_runs.c.spm_provenance.type
    assert isinstance(spm_type.dialect_impl(postgresql.dialect()), postgresql.JSONB)
    assert report_runs.c.data_version.nullable
    assert report_runs.c.data_version.type.length == 128
    assert {"labor_supply_result", "cliff_impact_result"}.isdisjoint(
        report_runs.c.keys()
    )


def test_labor_supply_responses_have_one_typed_row_per_report_run() -> None:
    responses = V2_METADATA.tables["labor_supply_responses"]

    assert set(responses.c.keys()) == {
        "id",
        "created_at",
        "report_run_id",
        *LABOR_SUPPLY_RESPONSE_COLUMNS,
    }
    for column_name in LABOR_SUPPLY_RESPONSE_COLUMNS:
        assert not responses.c[column_name].nullable, column_name
        assert isinstance(responses.c[column_name].type, sa.Float), column_name
    report_run_key = _foreign_key(responses, "report_run_id")
    assert report_run_key.target_fullname == "report_runs.id"
    assert report_run_key.ondelete == "CASCADE"
    assert _unique_column_sets(responses) == {("report_run_id",)}


def test_labor_supply_decile_responses_have_one_row_per_decile() -> None:
    deciles = V2_METADATA.tables["labor_supply_decile_responses"]

    assert set(deciles.c.keys()) == {
        "id",
        "created_at",
        "report_run_id",
        "decile",
        *LABOR_SUPPLY_DECILE_COLUMNS,
    }
    assert not deciles.c.decile.nullable
    # .py reports a relative response only for deciles above zero.
    for column_name in LABOR_SUPPLY_DECILE_COLUMNS:
        assert deciles.c[column_name].nullable, column_name
        assert isinstance(deciles.c[column_name].type, sa.Float), column_name
    report_run_key = _foreign_key(deciles, "report_run_id")
    assert report_run_key.target_fullname == "report_runs.id"
    assert report_run_key.ondelete == "CASCADE"
    assert _unique_column_sets(deciles) == {("report_run_id", "decile")}


def test_report_run_relationships_name_labor_supply_rows() -> None:
    relationships = sa.inspect(ReportRun).relationships

    assert relationships["labor_supply_responses"].mapper.class_ is (
        LaborSupplyResponse
    )
    assert relationships["labor_supply_decile_responses"].mapper.class_ is (
        LaborSupplyDecileResponse
    )
    assert "comparisons" not in relationships
    assert LaborSupplyResponse.__module__.endswith(".run_results")


def test_uk_area_impacts_record_disclosure_control() -> None:
    for table_name in ("constituency_impacts", "local_authority_impacts"):
        table = V2_METADATA.tables[table_name]
        assert table.c.disclosure_tier.nullable
        assert table.c.disclosure_tier.type.length == 16
        for change in ("average", "relative"):
            for bound in ("lower", "upper"):
                column = table.c[f"{change}_household_income_change_{bound}"]
                assert column.nullable
                assert isinstance(column.type, sa.Float)
        assert f"ck_{table_name}_disclosure_tier" in _check_names(table)


def test_withheld_area_codes_list_each_area_a_report_run_held_back() -> None:
    """One row per UK area that disclosure control withheld from a report run."""
    withheld = V2_METADATA.tables["withheld_area_codes"]

    assert set(withheld.c.keys()) == {
        "id",
        "created_at",
        "report_run_id",
        "baseline_simulation_run_id",
        "reform_simulation_run_id",
        "area_type",
        "code",
    }
    area_type = withheld.c.area_type
    assert not area_type.nullable
    assert isinstance(area_type.type, sa.Enum)
    assert area_type.type.name == "v2_uk_area_type"
    assert area_type.type.enums == ["constituency", "local_authority"]
    assert not withheld.c.code.nullable
    assert withheld.c.code.type.length == 64
    assert {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in withheld.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {
        "uq_withheld_area_codes_run_type_code": (
            "report_run_id",
            "area_type",
            "code",
        )
    }
    relationship = sa.inspect(ReportRun).relationships["withheld_area_codes"]
    assert relationship.mapper.local_table is withheld
    assert "delete" in relationship.cascade


def test_congressional_district_impacts_record_winner_and_loser_shares() -> None:
    districts = V2_METADATA.tables["congressional_district_impacts"]

    for column_name in (
        "winner_percentage",
        "loser_percentage",
        "no_change_percentage",
    ):
        assert not districts.c[column_name].nullable
        assert isinstance(districts.c[column_name].type, sa.Float)


def test_detailed_budget_rows_need_neither_an_entity_nor_a_tax_flag() -> None:
    """The economy output names each program's totals, not its entity or kind."""
    program_statistics = V2_METADATA.tables["program_statistics"]

    assert program_statistics.c.entity.nullable
    assert program_statistics.c.is_tax.nullable
    statement = str(
        CreateTable(program_statistics).compile(dialect=postgresql.dialect())
    )
    assert (
        "CONSTRAINT uq_program_statistics_run_program_entity UNIQUE NULLS NOT "
        "DISTINCT (report_run_id, program_name, entity)"
    ) in statement


def test_report_runs_name_their_baseline_and_reform_simulation_runs() -> None:
    """A report run compares one pair; a household report may have no reform."""
    report_runs = V2_METADATA.tables["report_runs"]

    assert not report_runs.c.baseline_simulation_run_id.nullable
    assert report_runs.c.reform_simulation_run_id.nullable
    for column_name in ("baseline_simulation_run_id", "reform_simulation_run_id"):
        run_key = _foreign_key(report_runs, column_name)
        assert run_key.target_fullname == "simulation_runs.id"
        assert run_key.ondelete == "RESTRICT"
        assert (column_name,) in _indexes(report_runs).values()
    assert "report_run_simulation_runs" not in V2_METADATA.tables
    enum_type_names = {
        column.type.name
        for table in V2_METADATA.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.Enum)
    }
    assert "v2_simulation_role" not in enum_type_names


def test_budget_window_reports_name_how_many_years_they_compare() -> None:
    reports = V2_METADATA.tables["reports"]

    assert reports.c.budget_window_size.nullable
    assert isinstance(reports.c.budget_window_size.type, sa.Integer)
    assert "ck_reports_budget_window_size" in _check_names(reports)


def test_budget_window_runs_record_each_calculation_of_a_window() -> None:
    windows = V2_METADATA.tables["budget_window_runs"]

    required = {
        "report_id",
        "tax_benefit_model_version_id",
        "recalculate",
        "status",
        "created_at",
        "updated_at",
    }
    optional = {
        "error_message",
        "started_at",
        "completed_at",
        "policyengine_version",
        "trigger",
    }
    assert set(windows.c.keys()) == {"id"} | required | optional
    assert all(not windows.c[name].nullable for name in required)
    assert all(windows.c[name].nullable for name in optional)
    # A window run has a report run's states and starts for a report run's reasons.
    assert windows.c.status.type.name == "v2_report_run_status"
    assert windows.c.trigger.type.name == "v2_report_run_trigger"
    report_key = _foreign_key(windows, "report_id")
    assert report_key.target_fullname == "reports.id"
    assert report_key.ondelete == "CASCADE"
    version_key = _foreign_key(windows, "tax_benefit_model_version_id")
    assert version_key.target_fullname == "tax_benefit_model_versions.id"
    assert version_key.ondelete == "RESTRICT"
    assert ("id", "report_id") in _unique_column_sets(windows)
    assert "ck_budget_window_runs_terminal_completion" in _check_names(windows)
    assert _indexes(windows)["ix_budget_window_runs_report_id_created_at"] == (
        "report_id",
        "created_at",
    )
    assert BudgetWindowRun.__module__.endswith(".reports")


def test_report_runs_hold_one_year_of_a_budget_window_run() -> None:
    report_runs = V2_METADATA.tables["report_runs"]

    assert report_runs.c.budget_window_run_id.nullable
    assert report_runs.c.year.nullable
    (window_key,) = (
        constraint
        for constraint in report_runs.foreign_key_constraints
        if constraint.referred_table.name == "budget_window_runs"
    )
    # A year's report run belongs to a window run of the same report, which
    # owns it as the report owns its runs.
    assert [column.name for column in window_key.columns] == [
        "budget_window_run_id",
        "report_id",
    ]
    assert [element.target_fullname for element in window_key.elements] == [
        "budget_window_runs.id",
        "budget_window_runs.report_id",
    ]
    assert window_key.ondelete == "CASCADE"
    assert ("budget_window_run_id", "year") in _unique_column_sets(report_runs)
    assert {"ck_report_runs_year", "ck_report_runs_budget_window_year"} <= (
        _check_names(report_runs)
    )


def test_household_jobs_calculate_one_household_year_and_policy() -> None:
    household_jobs = V2_METADATA.tables["household_jobs"]

    for column_name in (
        "household_id",
        "year",
        "tax_benefit_model_version_id",
        "country_package_version",
        "policyengine_version",
        "request_data",
        "updated_at",
    ):
        assert not household_jobs.c[column_name].nullable, column_name
    for column_name in ("policy_id", "dynamic_id", "modal_call_id"):
        assert household_jobs.c[column_name].nullable, column_name
    assert household_jobs.c.modal_call_id.type.length == 255
    assert "ck_household_jobs_year" in _check_names(household_jobs)
    assert "ix_household_jobs_household_id" in _indexes(household_jobs)
    assert _foreign_key(household_jobs, "household_id").target_fullname == (
        "households.id"
    )
    assert _foreign_key(
        household_jobs, "tax_benefit_model_version_id"
    ).target_fullname == ("tax_benefit_model_versions.id")


def test_per_simulation_results_belong_to_one_simulation_run() -> None:
    for table_name in PER_SIMULATION_RESULT_TABLES:
        table = V2_METADATA.tables[table_name]
        assert {"report_run_id", "simulation_id"}.isdisjoint(table.c.keys())
        assert not table.c.simulation_run_id.nullable
        simulation_run_key = _foreign_key(table, "simulation_run_id")
        assert simulation_run_key.target_fullname == "simulation_runs.id"
        assert simulation_run_key.ondelete == "CASCADE"

    assert _unique_column_sets(V2_METADATA.tables["inequality"]) == {
        ("simulation_run_id", "income_variable", "entity")
    }
    assert _unique_column_sets(V2_METADATA.tables["poverty"]) == {
        (
            "simulation_run_id",
            "poverty_type",
            "entity",
            "filter_variable",
            "filter_group",
        )
    }


def test_poverty_rows_without_a_filter_variable_are_unique_per_run() -> None:
    statement = str(
        CreateTable(V2_METADATA.tables["poverty"]).compile(dialect=postgresql.dialect())
    )

    assert (
        "CONSTRAINT uq_poverty_simulation_run_measure UNIQUE NULLS NOT DISTINCT "
        "(simulation_run_id, poverty_type, entity, filter_variable, filter_group)"
    ) in statement


def test_comparison_results_name_the_two_simulation_runs_they_compare() -> None:
    for table_name in COMPARISON_RESULT_TABLES:
        table = V2_METADATA.tables[table_name]
        assert {"baseline_simulation_id", "reform_simulation_id"}.isdisjoint(
            table.c.keys()
        ), table_name
        report_run_key = _foreign_key(table, "report_run_id")
        assert report_run_key.target_fullname == "report_runs.id"
        assert report_run_key.ondelete == "CASCADE"
        for column_name in ("baseline_simulation_run_id", "reform_simulation_run_id"):
            assert not table.c[column_name].nullable
            run_key = _foreign_key(table, column_name)
            assert run_key.target_fullname == "simulation_runs.id", table_name
            assert run_key.ondelete == "RESTRICT"
        # A report run compares one pair of simulation runs, so each row is
        # unique within its report run.
        (unique_columns,) = _unique_column_sets(table)
        assert unique_columns[0] == "report_run_id", table_name
        assert {"baseline_simulation_run_id", "reform_simulation_run_id"}.isdisjoint(
            unique_columns
        ), table_name


def test_custom_totals_keep_their_simulation_references() -> None:
    """``aggregates`` and ``change_aggregates`` stay unchanged until they return."""
    aggregates = V2_METADATA.tables["aggregates"]
    change_aggregates = V2_METADATA.tables["change_aggregates"]

    assert _foreign_key(aggregates, "simulation_id").target_fullname == (
        "simulations.id"
    )
    for column_name in ("baseline_simulation_id", "reform_simulation_id"):
        assert _foreign_key(change_aggregates, column_name).target_fullname == (
            "simulations.id"
        )
    for table in (aggregates, change_aggregates):
        assert _foreign_key(table, "report_run_id").target_fullname == (
            "report_runs.id"
        )


def test_simulation_tables_keep_foreign_keys_to_the_rows_they_name() -> None:
    """Each service writes only its own tables; the keys between them stay."""
    public_api_keys = {
        (table.name, key.parent.name): (key.column.table.name, key.ondelete)
        for table in V2_METADATA.tables.values()
        if table.name in SIMULATION_SIDE_TABLES
        for key in table.foreign_keys
        if key.column.table.name not in SIMULATION_SIDE_TABLES
    }

    assert public_api_keys == PUBLIC_API_FOREIGN_KEYS
    assert set(V2_METADATA.tables) >= SIMULATION_SIDE_TABLES


def test_reports_index_their_owner_for_account_deletion() -> None:
    """Deleting a user clears ``reports.user_id``, which an index finds."""
    reports = V2_METADATA.tables["reports"]

    assert ("user_id",) in _indexes(reports).values()


def test_the_catalog_versions_runs_and_jobs_use_are_indexed() -> None:
    for table_name in ("simulation_runs", "household_jobs"):
        table = V2_METADATA.tables[table_name]
        assert ("tax_benefit_model_version_id",) in _indexes(table).values(), table_name


def test_poverty_rows_name_the_group_their_filter_selects() -> None:
    """One filter variable selects several groups (``age``: child, adult, senior)."""
    poverty = V2_METADATA.tables["poverty"]

    assert poverty.c.filter_group.nullable
    assert poverty.c.filter_group.type.length == 64


def test_decile_rows_name_the_variable_that_groups_them() -> None:
    """Wealth deciles of income changes share the income variable and entity."""
    decile_impacts = V2_METADATA.tables["decile_impacts"]

    assert decile_impacts.c.decile_variable.nullable
    assert decile_impacts.c.decile_variable.type.length == 512
    statement = str(CreateTable(decile_impacts).compile(dialect=postgresql.dialect()))
    assert (
        "CONSTRAINT uq_decile_impacts_run_measure UNIQUE NULLS NOT DISTINCT "
        "(report_run_id, income_variable, decile_variable, entity, decile, quantiles)"
    ) in statement
