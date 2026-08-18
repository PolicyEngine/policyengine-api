"""Structural contract tests for the complete reviewed v2 SQLModel schema."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from policyengine_api.data.v1_models import V1Base
from policyengine_api.data.v2.models import (
    Dynamic,
    Household,
    HouseholdJob,
    Policy,
    Simulation,
    User,
    UserHouseholdAssociation,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
    V2_METADATA,
    V2_TABLE_MODELS,
)
from policyengine_api.data.v2.table_inventory import EXPECTED_V2_TABLES


RUN_OUTPUT_TABLES = frozenset(
    {
        "aggregates",
        "budget_summary",
        "change_aggregates",
        "congressional_district_impacts",
        "constituency_impacts",
        "decile_impacts",
        "inequality",
        "intra_decile_impacts",
        "local_authority_impacts",
        "poverty",
        "program_statistics",
    }
)


def test_domain_models_are_grouped_into_topic_scoped_modules() -> None:
    expected_modules = {
        User: "users",
        Policy: "policies",
        Dynamic: "policies",
        Household: "households",
        HouseholdJob: "households",
        Simulation: "simulations",
        UserHouseholdAssociation: "associations",
        UserPolicy: "associations",
        UserReportAssociation: "associations",
        UserSimulationAssociation: "associations",
    }

    assert {
        model: model.__module__.rsplit(".", maxsplit=1)[-1]
        for model in expected_modules
    } == expected_modules


def test_controlled_models_match_the_exact_reviewed_inventory() -> None:
    model_table_names = {model.__table__.name for model in V2_TABLE_MODELS}

    assert V2_METADATA is not V1Base.metadata
    assert set(V2_METADATA.tables) == EXPECTED_V2_TABLES
    assert model_table_names == EXPECTED_V2_TABLES
    assert len(V2_TABLE_MODELS) == len(EXPECTED_V2_TABLES)


def test_every_table_has_named_primary_foreign_and_relational_constraints() -> None:
    for table in V2_METADATA.tables.values():
        assert table.primary_key.columns
        assert table.primary_key.name
        for constraint in table.constraints:
            assert constraint.name, f"unnamed constraint on {table.name}"
        for index in table.indexes:
            assert index.name, f"unnamed index on {table.name}"
        for foreign_key in table.foreign_keys:
            assert foreign_key.constraint.name
            assert foreign_key.ondelete in {"CASCADE", "RESTRICT", "SET NULL"}
            assert foreign_key.column.table.name in EXPECTED_V2_TABLES


def test_every_declared_relationship_has_a_complete_back_populates_pair() -> None:
    configure_mappers()

    for model in V2_TABLE_MODELS:
        mapper = sa.inspect(model)
        for relationship in mapper.relationships:
            assert relationship.back_populates, (
                f"{model.__name__}.{relationship.key} lacks back_populates"
            )
            inverse = relationship.mapper.relationships[relationship.back_populates]
            assert inverse.back_populates == relationship.key
            assert inverse.mapper is mapper


def test_every_user_association_has_relational_integrity() -> None:
    configure_mappers()
    user_mapper = sa.inspect(User)
    associations = (
        (
            UserHouseholdAssociation,
            "user_household_associations",
            "household_associations",
        ),
        (UserPolicy, "user_policies", "policy_associations"),
        (
            UserSimulationAssociation,
            "user_simulation_associations",
            "simulation_associations",
        ),
        (UserReportAssociation, "user_report_associations", "report_associations"),
    )

    for model, table_name, user_collection in associations:
        user_id = V2_METADATA.tables[table_name].c.user_id
        foreign_keys = list(user_id.foreign_keys)
        assert len(foreign_keys) == 1
        assert foreign_keys[0].target_fullname == "users.id"
        assert foreign_keys[0].ondelete == "CASCADE"

        association_user = sa.inspect(model).relationships["user"]
        assert association_user.back_populates == user_collection
        assert user_mapper.relationships[user_collection].back_populates == "user"


def test_all_datetime_columns_are_timezone_aware() -> None:
    datetime_columns = [
        column
        for table in V2_METADATA.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.DateTime)
    ]

    assert datetime_columns
    assert all(column.type.timezone for column in datetime_columns)


def test_report_definition_and_run_columns_are_separated() -> None:
    report = V2_METADATA.tables["reports"]
    report_run = V2_METADATA.tables["report_runs"]

    assert report.c.type.nullable
    assert {
        "country",
        "type",
        "tax_benefit_model_id",
        "policy_id",
        "baseline_simulation_id",
        "reform_simulation_id",
        "household_id",
        "dataset_id",
        "region_id",
        "year",
        "inputs",
    }.issubset(report.c.keys())
    assert {
        "country_package_version",
        "policyengine_version",
        "status",
        "trigger",
        "idempotency_key",
        "started_at",
        "completed_at",
        "error_message",
        "markdown",
    }.issubset(report_run.c.keys())
    assert {
        "country_package_version",
        "policyengine_version",
        "status",
        "error_message",
        "markdown",
    }.isdisjoint(report.c.keys())
    assert not report_run.c.country_package_version.nullable
    assert not report_run.c.policyengine_version.nullable
    assert isinstance(report_run.c.idempotency_key.type, sa.Uuid)
    assert report_run.c.idempotency_key.type.as_uuid


def test_user_primary_country_is_required_and_limited_to_supported_values() -> None:
    users = V2_METADATA.tables["users"]

    assert not users.c.primary_country.nullable
    assert users.c.primary_country.type.length == 2
    assert "ck_users_primary_country" in {
        constraint.name for constraint in users.constraints
    }


def test_run_outputs_reference_report_runs_not_base_reports() -> None:
    for table_name in RUN_OUTPUT_TABLES:
        table = V2_METADATA.tables[table_name]
        assert "report_run_id" in table.c
        assert not table.c.report_run_id.nullable
        assert "report_id" not in table.c
        foreign_key = next(iter(table.c.report_run_id.foreign_keys))
        assert foreign_key.target_fullname == "report_runs.id"
        assert foreign_key.ondelete == "CASCADE"


def test_report_rerun_constraints_allow_same_versions_but_deduplicate_requests() -> (
    None
):
    report_runs = V2_METADATA.tables["report_runs"]
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in report_runs.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }

    assert ("report_id", "idempotency_key") in unique_column_sets
    assert (
        "report_id",
        "country_package_version",
        "policyengine_version",
    ) not in unique_column_sets
    assert "ix_report_runs_current_output" in {
        index.name for index in report_runs.indexes
    }


def test_named_checks_and_required_indexes_cover_core_invariants() -> None:
    constraint_names = {
        constraint.name
        for table in V2_METADATA.tables.values()
        for constraint in table.constraints
    }
    index_names = {
        index.name for table in V2_METADATA.tables.values() for index in table.indexes
    }

    assert {
        "ck_regions_required_filter_values",
        "ck_simulations_type_input",
        "ck_users_primary_country",
        "ck_report_runs_terminal_completion",
        "ck_parameter_values_single_owner",
    }.issubset(constraint_names)
    assert {
        "ix_users_email",
        "ix_simulations_status_created_at",
        "ix_report_runs_current_output",
    }.issubset(index_names)


def test_complete_metadata_compiles_for_postgres_without_mutation() -> None:
    dialect = postgresql.dialect()

    statements = [
        str(CreateTable(table).compile(dialect=dialect))
        for table in V2_METADATA.sorted_tables
    ]

    assert len(statements) == len(EXPECTED_V2_TABLES)
    assert all("CREATE TABLE" in statement for statement in statements)
