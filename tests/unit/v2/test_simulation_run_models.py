"""Structural tests for simulation runs, report runs, household jobs and results.

A simulation defines what to calculate and each calculation of it is a run that
records the catalog and PolicyEngine.py versions it used. A report run names
its baseline and reform simulation runs, results are keyed by run, and a
household job calculates one household for one year under one policy.

Columns are read from the models' mappers, and keys, constraints and indexes
from SQLite's copy of the schema (tests/unit/v2/v2_schema_reading.py), as are
the columns a mapper leaves out, such as a report run's four older cliff
columns.
"""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    LaborSupplyDecileResponse,
    LaborSupplyResponse,
    Report,
    ReportRun,
    SimulationRun,
    User,
)
from tests.fixtures.database_sessions import (
    recorded_statements,
    sqlite_v2_sessions,
    v2_schema_statements,
)
from tests.unit.v2.v2_schema_reading import (
    StoredForeignKeyColumn,
    model_columns,
    stored_v2_schema,
    stored_v2_table,
    v2_mappers,
    v2_model,
)

RUN_STATUSES = ["pending", "running", "succeeded", "failed"]
# A report run's cliffs are its simulation runs' cliff results, not its columns.
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
# A simulation run's cliff calculation is one of its results too.
PER_SIMULATION_RESULT_TABLES = ("inequality", "poverty", "cliff_impacts")
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
# The tables the simulation service and its Modal workers write. API v1
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
# The foreign keys from the simulation service's tables to API v1's rows,
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


def _foreign_key(table_name: str, column_name: str) -> StoredForeignKeyColumn:
    return stored_v2_table(table_name).foreign_key(column_name)


def _check_names(table_name: str) -> set[str | None]:
    return set(stored_v2_table(table_name).checks)


def _unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    return stored_v2_table(table_name).unique_column_sets


def _indexes(table_name: str) -> dict[str | None, tuple[str | None, ...]]:
    return stored_v2_table(table_name).index_columns


def _create_table_statement(table_name: str) -> str:
    """Return the CREATE TABLE statement the v2 schema sends PostgreSQL."""
    return next(
        statement
        for statement in v2_schema_statements("postgresql")
        if statement.lstrip().startswith(f"CREATE TABLE {table_name} (")
    )


def test_simulations_keep_only_what_to_calculate() -> None:
    simulations = model_columns("simulations")

    assert {
        "status",
        "error_message",
        "started_at",
        "completed_at",
        "household_result",
        "output_dataset_id",
    }.isdisjoint(simulations.keys())
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
    } <= set(simulations.keys())
    assert "ix_simulations_status_created_at" not in _indexes("simulations")


def test_each_simulation_run_records_its_versions_status_and_output() -> None:
    simulation_runs = model_columns("simulation_runs")

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
    assert set(simulation_runs.keys()) == {"id"} | required | optional
    assert all(not simulation_runs[name].nullable for name in required)
    assert all(simulation_runs[name].nullable for name in optional)
    assert simulation_runs.status.type.name == "v2_simulation_status"
    assert list(simulation_runs.status.type.enums) == RUN_STATUSES
    assert simulation_runs.modal_call_id.type.length == 255
    assert simulation_runs.output_uri.type.length == 2048
    assert simulation_runs.output_sha256.type.length == 64
    assert simulation_runs.country_package_version.type.length == 128
    assert simulation_runs.policyengine_version.type.length == 128

    simulation_key = _foreign_key("simulation_runs", "simulation_id")
    assert simulation_key.target == "simulations.id"
    assert simulation_key.ondelete == "CASCADE"
    stored_keys = stored_v2_table("simulation_runs").foreign_key_columns
    assert {key.target for key in stored_keys} == {
        "simulations.id",
        "tax_benefit_model_versions.id",
        "datasets.id",
        "regions.id",
    }
    assert "ck_simulation_runs_year" in _check_names("simulation_runs")
    assert SimulationRun.__module__.endswith(".simulations")


def test_run_tables_require_a_completion_time_and_index_running_runs() -> None:
    assert {
        "ck_simulation_runs_terminal_completion",
        "ck_simulation_runs_output_pair",
        "ck_simulation_runs_output_sha256_length",
    } <= _check_names("simulation_runs")
    assert "ck_household_jobs_terminal_completion" in _check_names("household_jobs")
    # A simulation has a run per year, so its newest successful run is found
    # per year.
    assert _indexes("simulation_runs") == {
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
    assert _indexes("report_runs")["ix_report_runs_status_started_at"] == (
        "status",
        "started_at",
    )


def test_report_runs_record_their_modal_call() -> None:
    report_runs = model_columns("report_runs")

    assert report_runs.modal_call_id.nullable
    assert report_runs.modal_call_id.type.length == 255
    assert "report_run_comparisons" not in stored_v2_schema()


def test_report_runs_record_their_spm_receipt_and_data_version_but_no_cliffs() -> None:
    """The comparison parts with no result table are typed, except the receipt."""
    report_runs = model_columns("report_runs")
    stored_columns = stored_v2_table("report_runs").columns

    assert set(stored_columns).isdisjoint(CLIFF_IMPACT_COLUMNS)
    assert "ck_report_runs_cliff_impact_complete" not in _check_names("report_runs")
    assert report_runs.spm_provenance.nullable
    spm_type = report_runs.spm_provenance.type
    assert isinstance(spm_type.dialect_impl(postgresql.dialect()), postgresql.JSONB)
    assert report_runs.data_version.nullable
    assert report_runs.data_version.type.length == 128
    assert {"labor_supply_result", "cliff_impact_result"}.isdisjoint(report_runs.keys())


def test_report_runs_load_none_of_their_cliff_columns() -> None:
    """A run's cliffs are its simulation runs', so API v1 leaves these columns alone.

    They stay SQLModel fields, as rule ``api.data.orm-only`` requires of every
    column, with no Core column of their own, and the mapper leaves them out
    until a revision drops them.
    """
    loaded_columns = str(sa.select(ReportRun).compile(dialect=postgresql.dialect()))

    assert [name for name in CLIFF_IMPACT_COLUMNS if name in loaded_columns] == []
    assert set(CLIFF_IMPACT_COLUMNS).isdisjoint(
        sa.inspect(ReportRun).column_attrs.keys()
    )
    assert set(CLIFF_IMPACT_COLUMNS) <= set(ReportRun.model_fields)
    core_columns = [
        argument
        for argument in ReportRun.__table_args__
        if isinstance(argument, sa.Column)
    ]
    assert core_columns == []


def test_storing_a_report_run_writes_none_of_its_cliff_columns() -> None:
    report_run = ReportRun(
        report_id=uuid4(),
        baseline_simulation_run_id=uuid4(),
        reform_simulation_run_id=uuid4(),
        country_package_version="1.0.0",
        policyengine_version="4.2.0",
        baseline_cliff_gap=1.5,
        baseline_cliff_share=0.1,
        reform_cliff_gap=2.5,
        reform_cliff_share=0.2,
    )

    with (
        sqlite_v2_sessions() as sessions,
        recorded_statements(sessions) as statements,
        sessions.begin() as session,
    ):
        session.add(report_run)

    (stored,) = [statement for statement in statements if "INSERT" in statement]
    assert "report_runs" in stored
    assert [name for name in CLIFF_IMPACT_COLUMNS if name in stored] == []


def test_labor_supply_responses_have_one_typed_row_per_report_run() -> None:
    responses = model_columns("labor_supply_responses")

    assert set(responses.keys()) == {
        "id",
        "created_at",
        "report_run_id",
        *LABOR_SUPPLY_RESPONSE_COLUMNS,
    }
    for column_name in LABOR_SUPPLY_RESPONSE_COLUMNS:
        assert not responses[column_name].nullable, column_name
        assert isinstance(responses[column_name].type, sa.Float), column_name
    report_run_key = _foreign_key("labor_supply_responses", "report_run_id")
    assert report_run_key.target == "report_runs.id"
    assert report_run_key.ondelete == "CASCADE"
    assert _unique_column_sets("labor_supply_responses") == {("report_run_id",)}


def test_labor_supply_decile_responses_have_one_row_per_decile() -> None:
    deciles = model_columns("labor_supply_decile_responses")

    assert set(deciles.keys()) == {
        "id",
        "created_at",
        "report_run_id",
        "decile",
        *LABOR_SUPPLY_DECILE_COLUMNS,
    }
    assert not deciles.decile.nullable
    # .py reports a relative response only for deciles above zero.
    for column_name in LABOR_SUPPLY_DECILE_COLUMNS:
        assert deciles[column_name].nullable, column_name
        assert isinstance(deciles[column_name].type, sa.Float), column_name
    report_run_key = _foreign_key("labor_supply_decile_responses", "report_run_id")
    assert report_run_key.target == "report_runs.id"
    assert report_run_key.ondelete == "CASCADE"
    assert _unique_column_sets("labor_supply_decile_responses") == {
        ("report_run_id", "decile")
    }


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
        columns = model_columns(table_name)
        assert columns.disclosure_tier.nullable
        assert columns.disclosure_tier.type.length == 16
        for change in ("average", "relative"):
            for bound in ("lower", "upper"):
                column = columns[f"{change}_household_income_change_{bound}"]
                assert column.nullable
                assert isinstance(column.type, sa.Float)
        assert f"ck_{table_name}_disclosure_tier" in _check_names(table_name)


def test_withheld_area_codes_list_each_area_a_report_run_held_back() -> None:
    """One row per UK area that disclosure control withheld from a report run."""
    withheld = model_columns("withheld_area_codes")

    assert set(withheld.keys()) == {
        "id",
        "created_at",
        "report_run_id",
        "baseline_simulation_run_id",
        "reform_simulation_run_id",
        "area_type",
        "code",
    }
    area_type = withheld.area_type
    assert not area_type.nullable
    assert isinstance(area_type.type, sa.Enum)
    assert area_type.type.name == "v2_uk_area_type"
    assert area_type.type.enums == ["constituency", "local_authority"]
    assert not withheld.code.nullable
    assert withheld.code.type.length == 64
    assert stored_v2_table("withheld_area_codes").unique_constraints == {
        "uq_withheld_area_codes_run_type_code": (
            "report_run_id",
            "area_type",
            "code",
        )
    }
    relationship = sa.inspect(ReportRun).relationships["withheld_area_codes"]
    assert relationship.mapper.class_ is v2_model("withheld_area_codes")
    assert "delete" in relationship.cascade


def test_congressional_district_impacts_record_winner_and_loser_shares() -> None:
    districts = model_columns("congressional_district_impacts")

    for column_name in (
        "winner_percentage",
        "loser_percentage",
        "no_change_percentage",
    ):
        assert not districts[column_name].nullable
        assert isinstance(districts[column_name].type, sa.Float)


def test_detailed_budget_rows_need_neither_an_entity_nor_a_tax_flag() -> None:
    """The economy output names each program's totals, not its entity or kind."""
    program_statistics = model_columns("program_statistics")

    assert program_statistics.entity.nullable
    assert program_statistics.is_tax.nullable
    statement = _create_table_statement("program_statistics")
    assert (
        "CONSTRAINT uq_program_statistics_run_program_entity UNIQUE NULLS NOT "
        "DISTINCT (report_run_id, program_name, entity)"
    ) in statement


def test_report_runs_name_their_baseline_and_reform_simulation_runs() -> None:
    """A report run compares one pair; a household report may have no reform."""
    report_runs = model_columns("report_runs")

    assert not report_runs.baseline_simulation_run_id.nullable
    assert report_runs.reform_simulation_run_id.nullable
    for column_name in ("baseline_simulation_run_id", "reform_simulation_run_id"):
        run_key = _foreign_key("report_runs", column_name)
        assert run_key.target == "simulation_runs.id"
        assert run_key.ondelete == "RESTRICT"
        assert (column_name,) in _indexes("report_runs").values()
    assert "report_run_simulation_runs" not in stored_v2_schema()
    enum_type_names = {
        column.type.name
        for mapper in v2_mappers()
        for column in mapper.columns
        if isinstance(column.type, sa.Enum)
    }
    assert "v2_simulation_role" not in enum_type_names


def test_budget_window_reports_name_how_many_years_they_compare() -> None:
    reports = model_columns("reports")

    assert reports.budget_window_size.nullable
    assert isinstance(reports.budget_window_size.type, sa.Integer)
    assert "ck_reports_budget_window_size" in _check_names("reports")


def test_budget_window_runs_record_each_calculation_of_a_window() -> None:
    windows = model_columns("budget_window_runs")

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
    }
    assert set(windows.keys()) == {"id"} | required | optional
    assert all(not windows[name].nullable for name in required)
    assert all(windows[name].nullable for name in optional)
    # A window run has a report run's states.
    assert windows.status.type.name == "v2_report_run_status"
    report_key = _foreign_key("budget_window_runs", "report_id")
    assert report_key.target == "reports.id"
    assert report_key.ondelete == "CASCADE"
    version_key = _foreign_key("budget_window_runs", "tax_benefit_model_version_id")
    assert version_key.target == "tax_benefit_model_versions.id"
    assert version_key.ondelete == "RESTRICT"
    assert ("id", "report_id") in _unique_column_sets("budget_window_runs")
    assert "ck_budget_window_runs_terminal_completion" in _check_names(
        "budget_window_runs"
    )
    assert _indexes("budget_window_runs")[
        "ix_budget_window_runs_report_id_created_at"
    ] == (
        "report_id",
        "created_at",
    )
    assert BudgetWindowRun.__module__.endswith(".reports")


def test_report_runs_hold_one_year_of_a_budget_window_run() -> None:
    report_runs = model_columns("report_runs")

    assert report_runs.budget_window_run_id.nullable
    assert report_runs.year.nullable
    (window_key,) = stored_v2_table("report_runs").foreign_keys_to("budget_window_runs")
    # A year's report run belongs to a window run of the same report, which
    # owns it as the report owns its runs.
    assert window_key.columns == ("budget_window_run_id", "report_id")
    assert window_key.targets == (
        "budget_window_runs.id",
        "budget_window_runs.report_id",
    )
    assert window_key.ondelete == "CASCADE"
    assert ("budget_window_run_id", "year") in _unique_column_sets("report_runs")
    assert {"ck_report_runs_year", "ck_report_runs_budget_window_year"} <= (
        _check_names("report_runs")
    )


def test_household_jobs_calculate_one_household_year_and_policy() -> None:
    household_jobs = model_columns("household_jobs")

    for column_name in (
        "household_id",
        "year",
        "tax_benefit_model_version_id",
        "country_package_version",
        "policyengine_version",
        "request_data",
        "updated_at",
    ):
        assert not household_jobs[column_name].nullable, column_name
    for column_name in ("policy_id", "dynamic_id", "modal_call_id"):
        assert household_jobs[column_name].nullable, column_name
    assert household_jobs.modal_call_id.type.length == 255
    assert "ck_household_jobs_year" in _check_names("household_jobs")
    assert "ix_household_jobs_household_id" in _indexes("household_jobs")
    assert _foreign_key("household_jobs", "household_id").target == "households.id"
    assert _foreign_key("household_jobs", "tax_benefit_model_version_id").target == (
        "tax_benefit_model_versions.id"
    )


def test_per_simulation_results_belong_to_one_simulation_run() -> None:
    for table_name in PER_SIMULATION_RESULT_TABLES:
        columns = model_columns(table_name)
        assert {"report_run_id", "simulation_id"}.isdisjoint(columns.keys())
        assert not columns.simulation_run_id.nullable
        simulation_run_key = _foreign_key(table_name, "simulation_run_id")
        assert simulation_run_key.target == "simulation_runs.id"
        assert simulation_run_key.ondelete == "CASCADE"

    assert _unique_column_sets("inequality") == {
        ("simulation_run_id", "income_variable", "entity")
    }
    assert _unique_column_sets("poverty") == {
        (
            "simulation_run_id",
            "poverty_type",
            "entity",
            "filter_variable",
            "filter_group",
        )
    }


def test_poverty_rows_without_a_filter_variable_are_unique_per_run() -> None:
    statement = _create_table_statement("poverty")

    assert (
        "CONSTRAINT uq_poverty_simulation_run_measure UNIQUE NULLS NOT DISTINCT "
        "(simulation_run_id, poverty_type, entity, filter_variable, filter_group)"
    ) in statement


def test_comparison_results_name_the_two_simulation_runs_they_compare() -> None:
    for table_name in COMPARISON_RESULT_TABLES:
        columns = model_columns(table_name)
        assert {"baseline_simulation_id", "reform_simulation_id"}.isdisjoint(
            columns.keys()
        ), table_name
        report_run_key = _foreign_key(table_name, "report_run_id")
        assert report_run_key.target == "report_runs.id"
        assert report_run_key.ondelete == "CASCADE"
        for column_name in ("baseline_simulation_run_id", "reform_simulation_run_id"):
            assert not columns[column_name].nullable
            run_key = _foreign_key(table_name, column_name)
            assert run_key.target == "simulation_runs.id", table_name
            assert run_key.ondelete == "RESTRICT"
        # A report run compares one pair of simulation runs, so each row is
        # unique within its report run.
        (unique_columns,) = _unique_column_sets(table_name)
        assert unique_columns[0] == "report_run_id", table_name
        assert {"baseline_simulation_run_id", "reform_simulation_run_id"}.isdisjoint(
            unique_columns
        ), table_name


def test_custom_totals_keep_their_simulation_references() -> None:
    """``aggregates`` and ``change_aggregates`` stay unchanged until they return."""
    assert _foreign_key("aggregates", "simulation_id").target == "simulations.id"
    for column_name in ("baseline_simulation_id", "reform_simulation_id"):
        assert _foreign_key("change_aggregates", column_name).target == (
            "simulations.id"
        )
    for table_name in ("aggregates", "change_aggregates"):
        assert _foreign_key(table_name, "report_run_id").target == "report_runs.id"


def test_simulation_tables_keep_foreign_keys_to_the_rows_they_name() -> None:
    """Each service writes only its own tables; the keys between them stay."""
    tables = stored_v2_schema()
    public_api_keys = {
        (table.name, key.column): (key.referred_table, key.ondelete)
        for table in tables.values()
        if table.name in SIMULATION_SIDE_TABLES
        for key in table.foreign_key_columns
        if key.referred_table not in SIMULATION_SIDE_TABLES
    }

    assert public_api_keys == PUBLIC_API_FOREIGN_KEYS
    assert set(tables) >= SIMULATION_SIDE_TABLES


def test_reports_name_no_user() -> None:
    """A shared report has no owner, so deleting a user leaves it untouched."""
    assert "user_id" not in stored_v2_table("reports").columns
    assert ("user_id",) not in _indexes("reports").values()
    assert "user" not in Report.__sqlmodel_relationships__
    assert "reports" not in User.__sqlmodel_relationships__


def test_the_catalog_versions_runs_and_jobs_use_are_indexed() -> None:
    for table_name in ("simulation_runs", "household_jobs"):
        indexed_columns = _indexes(table_name).values()
        assert ("tax_benefit_model_version_id",) in indexed_columns, table_name


def test_poverty_rows_name_the_group_their_filter_selects() -> None:
    """One filter variable selects several groups (``age``: child, adult, senior)."""
    poverty = model_columns("poverty")

    assert poverty.filter_group.nullable
    assert poverty.filter_group.type.length == 64


def test_decile_rows_name_the_variable_that_groups_them() -> None:
    """Wealth deciles of income changes share the income variable and entity."""
    decile_impacts = model_columns("decile_impacts")

    assert decile_impacts.decile_variable.nullable
    assert decile_impacts.decile_variable.type.length == 512
    statement = _create_table_statement("decile_impacts")
    assert (
        "CONSTRAINT uq_decile_impacts_run_measure UNIQUE NULLS NOT DISTINCT "
        "(report_run_id, income_variable, decile_variable, entity, decile, quantiles)"
    ) in statement
