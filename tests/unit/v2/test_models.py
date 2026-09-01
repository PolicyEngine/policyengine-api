"""Structural contract tests for the complete reviewed v2 SQLModel schema."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from policyengine_api.data.v1_models import V1Base
from policyengine_api.data.v2.models import (
    DatasetVersion,
    Dynamic,
    Household,
    HouseholdJob,
    LegacyPolicyMapping,
    LegacyUserPolicyMapping,
    ParameterValue,
    Policy,
    Simulation,
    TaxBenefitModelVersion,
    User,
    UserHouseholdAssociation,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
    V2_METADATA,
)


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
        LegacyPolicyMapping: "policy_mappings",
        LegacyUserPolicyMapping: "policy_mappings",
        UserReportAssociation: "associations",
        UserSimulationAssociation: "associations",
    }

    assert {
        model: model.__module__.rsplit(".", maxsplit=1)[-1]
        for model in expected_modules
    } == expected_modules


def _v2_mappers():
    configure_mappers()
    return tuple(
        mapper
        for mapper in sa.inspect(User).registry.mappers
        if mapper.local_table is not None and mapper.local_table.metadata is V2_METADATA
    )


def test_every_metadata_table_has_one_mapped_model() -> None:
    metadata_table_names = set(V2_METADATA.tables)
    model_table_names = {mapper.local_table.name for mapper in _v2_mappers()}

    assert V2_METADATA is not V1Base.metadata
    assert model_table_names == metadata_table_names
    assert len(_v2_mappers()) == len(metadata_table_names)


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
            assert foreign_key.column.table.name in V2_METADATA.tables


def test_every_declared_relationship_has_a_complete_back_populates_pair() -> None:
    configure_mappers()

    for mapper in _v2_mappers():
        for relationship in mapper.relationships:
            assert relationship.back_populates, (
                f"{mapper.class_.__name__}.{relationship.key} lacks back_populates"
            )
            inverse = relationship.mapper.relationships[relationship.back_populates]
            assert inverse.back_populates == relationship.key
            assert inverse.mapper is mapper


def test_user_owned_associations_have_relational_integrity() -> None:
    configure_mappers()
    user_mapper = sa.inspect(User)
    associations = (
        (
            UserHouseholdAssociation,
            "user_household_associations",
            "household_associations",
        ),
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


def test_policy_content_identity_and_catalog_columns_are_explicit() -> None:
    policies = V2_METADATA.tables["policies"]

    assert {"name", "description"}.isdisjoint(policies.c.keys())
    assert {
        "country_id",
        "tax_benefit_model_id",
        "tax_benefit_model_version_id",
        "canonicalization_version",
        "content_hash",
        "created_at",
        "updated_at",
    }.issubset(policies.c.keys())
    assert policies.c.country_id.type.length == 2
    assert policies.c.content_hash.type.length == 64
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in policies.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("id", "country_id") in unique_columns
    assert ("canonicalization_version", "content_hash") in unique_columns
    assert {
        "ix_policies_country_model",
        "ix_policies_country_model_version",
    } <= {index.name for index in policies.indexes}


def test_policy_parameter_values_use_jsonb_and_enforce_period_identity() -> None:
    values = V2_METADATA.tables["parameter_values"]

    postgres_type = values.c.value_json.type.dialect_impl(postgresql.dialect())
    assert isinstance(postgres_type, postgresql.JSONB)
    assert {
        "ck_parameter_values_single_owner",
        "ck_parameter_values_effective_period",
    } <= {constraint.name for constraint in values.constraints}
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in values.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("policy_id", "parameter_id", "start_date") in unique_columns
    assert sa.inspect(ParameterValue).relationships["policy"].back_populates == (
        "parameter_values"
    )


def test_user_policy_is_an_independent_country_scoped_association() -> None:
    associations = V2_METADATA.tables["user_policies"]

    assert associations.c.user_id.type.length == 255
    assert list(associations.c.user_id.foreign_keys) == []
    assert {"country", "label"}.isdisjoint(associations.c.keys())
    assert {"country_id", "name", "description"}.issubset(associations.c.keys())
    assert associations.c.name.nullable
    assert associations.c.description.nullable
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in associations.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("user_id", "policy_id") not in unique_columns
    assert ("id", "country_id") in unique_columns
    policy_country = next(
        constraint
        for constraint in associations.foreign_key_constraints
        if constraint.name == "fk_user_policies_policy_country"
    )
    assert [column.name for column in policy_country.columns] == [
        "policy_id",
        "country_id",
    ]
    assert [element.target_fullname for element in policy_country.elements] == [
        "policies.id",
        "policies.country_id",
    ]
    assert policy_country.ondelete == "RESTRICT"


def test_legacy_policy_mapping_is_many_to_one_by_destination() -> None:
    mappings = V2_METADATA.tables["legacy_policy_mappings"]

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in mappings.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("country_id", "legacy_policy_id") in unique_columns
    assert ("policy_id",) not in unique_columns
    assert mappings.c.source_policy_hash.type.length == 255
    policy_country = next(iter(mappings.foreign_key_constraints))
    assert policy_country.name == "fk_legacy_policy_mappings_policy_country"
    assert policy_country.ondelete == "RESTRICT"


def test_legacy_user_policy_mapping_is_one_to_one_by_destination() -> None:
    mappings = V2_METADATA.tables["legacy_user_policy_mappings"]

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in mappings.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("country_id", "legacy_user_policy_id") in unique_columns
    assert ("user_policy_id",) in unique_columns
    assert mappings.c.fingerprint_sha256.type.length == 64
    assert mappings.c.last_applied_source_revision.server_default.arg == "0"
    assert "ck_legacy_user_policy_mappings_source_revision" in {
        constraint.name for constraint in mappings.constraints
    }
    association_country = next(iter(mappings.foreign_key_constraints))
    assert (
        association_country.name == "fk_legacy_user_policy_mappings_association_country"
    )
    assert association_country.ondelete == "CASCADE"


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


def test_regions_have_one_same_model_version_default_logical_dataset() -> None:
    regions = V2_METADATA.tables["regions"]
    datasets = V2_METADATA.tables["datasets"]

    assert "region_datasets" not in V2_METADATA.tables
    assert not regions.c.default_dataset_id.nullable
    assert regions.c.default_dataset_id.index
    default_constraint = next(
        constraint
        for constraint in regions.foreign_key_constraints
        if constraint.name == "fk_regions_default_dataset_model_version"
    )
    assert [element.parent.name for element in default_constraint.elements] == [
        "default_dataset_id",
        "tax_benefit_model_version_id",
    ]
    assert [element.target_fullname for element in default_constraint.elements] == [
        "datasets.id",
        "datasets.tax_benefit_model_version_id",
    ]
    assert default_constraint.ondelete == "RESTRICT"

    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in datasets.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("tax_benefit_model_version_id", "name") in unique_column_sets
    assert ("id", "tax_benefit_model_version_id") in unique_column_sets
    assert "tax_benefit_model_id" not in datasets.c
    assert "tax_benefit_model_id" not in regions.c
    assert not datasets.c.tax_benefit_model_version_id.nullable
    assert not regions.c.tax_benefit_model_version_id.nullable
    assert datasets.c.storage_path.nullable
    assert "ck_datasets_output_storage_path" in {
        constraint.name for constraint in datasets.constraints
    }


def test_reports_and_simulations_snapshot_selected_datasets() -> None:
    reports = V2_METADATA.tables["reports"]
    simulations = V2_METADATA.tables["simulations"]

    for table in (reports, simulations):
        dataset_foreign_key = next(iter(table.c.dataset_id.foreign_keys))
        assert dataset_foreign_key.target_fullname == "datasets.id"
        assert dataset_foreign_key.ondelete in {"RESTRICT", "SET NULL"}


def test_stage9_adds_no_dataset_version_relationship_to_run_tables() -> None:
    for table_name in ("simulations", "reports", "report_runs"):
        assert "dataset_version_id" not in V2_METADATA.tables[table_name].c


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
        "uq_parameter_values_canonical_parameter_start_date",
    }.issubset(index_names)


def test_stage9_uses_policyengine_version_as_its_only_catalog_release_identity() -> (
    None
):
    model_version = V2_METADATA.tables[TaxBenefitModelVersion.__tablename__]
    dataset_version = V2_METADATA.tables[DatasetVersion.__tablename__]
    forbidden_columns = {
        "policyengine_version",
        "core_version",
        "country_package_version",
        "dataset_release",
        "dataset_digest",
        "catalog_fingerprint",
    }

    assert set(model_version.c) >= {
        model_version.c.model_id,
        model_version.c.version,
        model_version.c.current_law_id,
        model_version.c.metadata_time_periods,
    }
    assert forbidden_columns.isdisjoint(model_version.c.keys())
    assert forbidden_columns.isdisjoint(dataset_version.c.keys())

    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in model_version.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("model_id", "version") in unique_column_sets


def test_canonical_parameter_values_have_a_postgres_partial_unique_index() -> None:
    parameter_values = V2_METADATA.tables["parameter_values"]
    index = next(
        index
        for index in parameter_values.indexes
        if index.name == "uq_parameter_values_canonical_parameter_start_date"
    )

    assert index.unique
    assert tuple(column.name for column in index.columns) == (
        "parameter_id",
        "start_date",
    )
    predicate = str(index.dialect_options["postgresql"]["where"])
    assert predicate == "policy_id IS NULL AND dynamic_id IS NULL"


def test_complete_metadata_compiles_for_postgres_without_mutation() -> None:
    dialect = postgresql.dialect()

    statements = [
        str(CreateTable(table).compile(dialect=dialect))
        for table in V2_METADATA.sorted_tables
    ]

    assert len(statements) == len(V2_METADATA.tables)
    assert all("CREATE TABLE" in statement for statement in statements)
