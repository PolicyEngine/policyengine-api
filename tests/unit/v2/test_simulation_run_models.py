"""Structural tests for simulation runs, report runs, household jobs and results.

A simulation defines what to calculate and each calculation of it is a run that
records the catalog and .py versions it used. A report run names the simulation
runs it combines, results are keyed by run, and a household job calculates one
household for one year under one policy.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from policyengine_api.data.v2.models import (
    V2_METADATA,
    ReportRunSimulationRun,
    SimulationRole,
    SimulationRun,
    User,
)

RUN_STATUSES = ["pending", "running", "succeeded", "failed"]
PER_SIMULATION_RESULT_TABLES = ("inequality", "poverty")
COMPARISON_RESULT_TABLES = (
    "budget_summary",
    "congressional_district_impacts",
    "constituency_impacts",
    "decile_impacts",
    "intra_decile_impacts",
    "local_authority_impacts",
    "program_statistics",
)
# The tables the simulation service and its Modal workers write. The Public API
# writes every other table.
SIMULATION_SIDE_TABLES = frozenset(
    {
        "simulations",
        "simulation_runs",
        "reports",
        "report_runs",
        "report_run_simulation_runs",
        "household_jobs",
        "aggregates",
        "change_aggregates",
        *PER_SIMULATION_RESULT_TABLES,
        *COMPARISON_RESULT_TABLES,
    }
)
# Columns naming the Public API's rows, which the simulation service checks
# before it writes the row that names them.
LOGICAL_REFERENCES = {
    "simulations": (
        "dataset_id",
        "household_id",
        "policy_id",
        "dynamic_id",
        "tax_benefit_model_version_id",
        "region_id",
    ),
    "reports": (
        "user_id",
        "tax_benefit_model_id",
        "policy_id",
        "household_id",
        "dataset_id",
        "region_id",
    ),
    "simulation_runs": ("tax_benefit_model_version_id", "dataset_id", "region_id"),
    "household_jobs": (
        "household_id",
        "policy_id",
        "dynamic_id",
        "tax_benefit_model_version_id",
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
        "tax_benefit_model_version_id",
        "country_package_version",
        "policyengine_version",
        "status",
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
    # The catalog version, dataset and region are the Public API's rows, so a
    # run refers to them without a foreign key.
    assert {key.target_fullname for key in simulation_runs.foreign_keys} == {
        "simulations.id"
    }
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
    assert _indexes(simulation_runs) == {
        "ix_simulation_runs_current_output": (
            "simulation_id",
            "status",
            "country_package_version",
            "policyengine_version",
            "completed_at",
            "id",
        ),
        "ix_simulation_runs_status_started_at": ("status", "started_at"),
    }
    assert _indexes(report_runs)["ix_report_runs_status_started_at"] == (
        "status",
        "started_at",
    )


def test_report_runs_record_their_modal_call_and_untabled_results() -> None:
    report_runs = V2_METADATA.tables["report_runs"]

    assert report_runs.c.modal_call_id.nullable
    assert report_runs.c.modal_call_id.type.length == 255
    for column_name in (
        "labor_supply_result",
        "cliff_impact_result",
        "spm_provenance",
    ):
        assert report_runs.c[column_name].nullable
        assert isinstance(report_runs.c[column_name].type, sa.JSON)
    assert report_runs.c.data_version.nullable
    assert report_runs.c.data_version.type.length == 128


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


def test_report_runs_name_the_simulation_runs_they_combine() -> None:
    members = V2_METADATA.tables["report_run_simulation_runs"]

    assert set(members.c.keys()) == {
        "id",
        "created_at",
        "report_run_id",
        "simulation_run_id",
        "role",
    }
    assert all(not column.nullable for column in members.columns)
    report_run_key = _foreign_key(members, "report_run_id")
    simulation_run_key = _foreign_key(members, "simulation_run_id")
    assert report_run_key.target_fullname == "report_runs.id"
    assert report_run_key.ondelete == "CASCADE"
    assert simulation_run_key.target_fullname == "simulation_runs.id"
    assert simulation_run_key.ondelete == "RESTRICT"
    assert members.c.role.type.name == "v2_simulation_role"
    assert list(members.c.role.type.enums) == ["baseline", "reform"]
    assert [role.value for role in SimulationRole] == ["baseline", "reform"]
    assert _unique_column_sets(members) == {
        ("report_run_id", "role", "simulation_run_id")
    }
    assert "ix_report_run_simulation_runs_simulation_run_id" in _indexes(members)
    assert ReportRunSimulationRun.__module__.endswith(".reports")


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
    assert "household_id" not in {
        key.parent.name for key in household_jobs.foreign_keys
    }
    assert "tax_benefit_model_version_id" not in {
        key.parent.name for key in household_jobs.foreign_keys
    }


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
        ("simulation_run_id", "poverty_type", "entity", "filter_variable")
    }


def test_poverty_rows_without_a_filter_variable_are_unique_per_run() -> None:
    statement = str(
        CreateTable(V2_METADATA.tables["poverty"]).compile(dialect=postgresql.dialect())
    )

    assert (
        "CONSTRAINT uq_poverty_simulation_run_measure UNIQUE NULLS NOT DISTINCT "
        "(simulation_run_id, poverty_type, entity, filter_variable)"
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
        assert any(
            columns[0] == "report_run_id" for columns in _unique_column_sets(table)
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


def test_no_foreign_key_joins_tables_that_different_services_write() -> None:
    """Each service checks the other service's rows its own rows name."""
    cross_service_keys = sorted(
        f"{table.name}.{key.parent.name} -> {key.column.table.name}"
        for table in V2_METADATA.tables.values()
        for key in table.foreign_keys
        if (table.name in SIMULATION_SIDE_TABLES)
        != (key.column.table.name in SIMULATION_SIDE_TABLES)
    )

    assert cross_service_keys == []
    assert set(V2_METADATA.tables) >= SIMULATION_SIDE_TABLES


def test_references_to_public_api_rows_stay_as_uuid_columns() -> None:
    for table_name, column_names in LOGICAL_REFERENCES.items():
        table = V2_METADATA.tables[table_name]
        for column_name in column_names:
            column = table.c[column_name]
            assert isinstance(column.type, sa.Uuid), f"{table_name}.{column_name}"
            assert not column.foreign_keys, f"{table_name}.{column_name}"


def test_no_relationship_joins_models_that_different_services_write() -> None:
    configure_mappers()
    cross_service_relationships = sorted(
        f"{mapper.class_.__name__}.{relationship.key}"
        for mapper in sa.inspect(User).registry.mappers
        if mapper.local_table is not None and mapper.local_table.metadata is V2_METADATA
        for relationship in mapper.relationships
        if (mapper.local_table.name in SIMULATION_SIDE_TABLES)
        != (relationship.mapper.local_table.name in SIMULATION_SIDE_TABLES)
    )

    assert cross_service_relationships == []
