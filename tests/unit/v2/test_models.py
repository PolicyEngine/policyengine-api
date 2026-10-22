"""Structural contract tests for the complete reviewed v2 SQLModel schema."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from policyengine_api.data.v1_models import V1Base
from policyengine_api.data.v2 import models as v2_models
from policyengine_api.data.v2.models import (
    V2_METADATA,
    DatasetVersion,
    Dynamic,
    Household,
    LegacyHouseholdMapping,
    LegacyPolicyMapping,
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    ParameterValue,
    Policy,
    TaxBenefitModelVersion,
    User,
    UserHouseholdAssociation,
    UserIdentity,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
    UserType,
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

# The simulation service owns these tables in its own schema. The v2 metadata
# still declares them, so it matches the schema until a later revision drops
# them, but no model maps them: nothing this release runs reads or writes them.
RETIRED_SIMULATION_TABLES = frozenset(
    {"household_jobs", "simulations", "reports", "report_runs", *RUN_OUTPUT_TABLES}
)
# Retired at Stage 12A; dropped by the same later revision.
RETIRED_ASSOCIATION_COLUMNS = frozenset({"country", "label"})
REMOVED_SIMULATION_MODEL_NAMES = frozenset(
    {
        "AggregateOutput",
        "AggregateType",
        "BudgetSummary",
        "ChangeAggregate",
        "CongressionalDistrictImpact",
        "ConstituencyImpact",
        "DecileImpact",
        "DecileType",
        "HouseholdJob",
        "HouseholdJobStatus",
        "Inequality",
        "IntraDecileImpact",
        "LocalAuthorityImpact",
        "OutputStatus",
        "Poverty",
        "ProgramStatistics",
        "Report",
        "ReportRun",
        "ReportRunStatus",
        "ReportRunTrigger",
        "Simulation",
        "SimulationStatus",
        "SimulationType",
    }
)


def test_domain_models_are_grouped_into_topic_scoped_modules() -> None:
    expected_modules = {
        User: "users",
        UserIdentity: "users",
        Policy: "policies",
        Dynamic: "policies",
        Household: "households",
        LegacyHouseholdMapping: "household_mappings",
        UserHouseholdAssociation: "associations",
        UserPolicy: "associations",
        LegacyPolicyMapping: "policy_mappings",
        LegacyUserMapping: "policy_mappings",
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


def test_every_kept_metadata_table_has_one_mapped_model() -> None:
    metadata_table_names = set(V2_METADATA.tables)
    model_table_names = {mapper.local_table.name for mapper in _v2_mappers()}

    assert V2_METADATA is not V1Base.metadata
    assert metadata_table_names >= RETIRED_SIMULATION_TABLES
    assert model_table_names == metadata_table_names - RETIRED_SIMULATION_TABLES
    assert len(_v2_mappers()) == len(model_table_names)


def test_models_package_exports_no_simulation_domain_model() -> None:
    exported_names = set(v2_models.__all__) | set(vars(v2_models))

    assert REMOVED_SIMULATION_MODEL_NAMES.isdisjoint(exported_names)


def test_kept_models_have_no_relationship_to_a_retired_table() -> None:
    related_tables = {
        f"{mapper.class_.__name__}.{relationship.key}": (
            relationship.mapper.local_table.name
        )
        for mapper in _v2_mappers()
        for relationship in mapper.relationships
    }

    assert not {
        relationship: table_name
        for relationship, table_name in related_tables.items()
        if table_name in RETIRED_SIMULATION_TABLES
    }


def test_association_models_do_not_map_the_retired_columns() -> None:
    for model in (UserSimulationAssociation, UserReportAssociation):
        table = V2_METADATA.tables[model.__tablename__]
        # Declared on the table, so the metadata matches the schema...
        assert set(table.c.keys()) >= RETIRED_ASSOCIATION_COLUMNS
        assert all(table.c[name].nullable for name in RETIRED_ASSOCIATION_COLUMNS)
        # ...but neither mapped nor a model field.
        assert RETIRED_ASSOCIATION_COLUMNS.isdisjoint(sa.inspect(model).columns.keys())
        assert RETIRED_ASSOCIATION_COLUMNS.isdisjoint(model.model_fields)


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
        (UserPolicy, "user_policies", "policy_associations"),
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

    assert isinstance(associations.c.user_id.type, sa.Uuid)
    user_foreign_key = next(iter(associations.c.user_id.foreign_keys))
    assert user_foreign_key.target_fullname == "users.id"
    assert user_foreign_key.ondelete == "CASCADE"
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
    assert sa.inspect(UserPolicy).relationships["user"].back_populates == (
        "policy_associations"
    )


def test_legacy_user_mapping_is_one_to_one() -> None:
    mappings = V2_METADATA.tables["legacy_user_mappings"]

    assert mappings.primary_key.columns.keys() == ["legacy_user_id"]
    assert mappings.c.legacy_user_id.type.length == 255
    assert mappings.c.created_at.type.timezone
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in mappings.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("user_id",) in unique_columns
    user_foreign_key = next(iter(mappings.c.user_id.foreign_keys))
    assert user_foreign_key.target_fullname == "users.id"
    assert user_foreign_key.ondelete == "RESTRICT"


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


def test_standard_users_require_a_supported_primary_country() -> None:
    users = V2_METADATA.tables["users"]

    # Nullable only for unauthenticated users; a check requires it otherwise.
    assert users.c.primary_country.nullable
    assert users.c.first_name.nullable
    assert users.c.last_name.nullable
    assert users.c.email.nullable
    assert users.c.primary_country.type.length == 2
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in users.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert checks == {
        "ck_users_primary_country": "primary_country IN ('us', 'uk')",
        "ck_users_user_type": "user_type IN ('unauthenticated', 'standard')",
        "ck_users_standard_primary_country": (
            "user_type = 'unauthenticated' OR primary_country IS NOT NULL"
        ),
    }


def test_user_type_defaults_to_standard_for_every_writer() -> None:
    users = V2_METADATA.tables["users"]

    assert not users.c.user_type.nullable
    assert users.c.user_type.type.length == 16
    # The server default covers inserts by Public API revisions that predate
    # the column; the Python default covers this revision's ORM inserts.
    assert users.c.user_type.server_default.arg == "standard"
    assert User().user_type == "standard"
    assert [member.value for member in UserType] == ["unauthenticated", "standard"]


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
        "ck_users_primary_country",
        "ck_parameter_values_single_owner",
    }.issubset(constraint_names)
    assert {
        "ix_users_email",
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


def test_user_identity_maps_one_issuer_subject_to_one_user() -> None:
    identities = V2_METADATA.tables["user_identities"]

    unique_columns = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in identities.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert unique_columns == {
        "uq_user_identities_issuer_subject": ("issuer", "subject")
    }
    assert isinstance(identities.c.issuer.type, sa.Text)
    assert isinstance(identities.c.subject.type, sa.Text)
    assert identities.c.email.nullable
    assert identities.c.email.type.length == 320
    assert not identities.c.last_seen_at.nullable
    user_foreign_key = next(iter(identities.c.user_id.foreign_keys))
    assert user_foreign_key.target_fullname == "users.id"
    assert user_foreign_key.ondelete == "CASCADE"
    assert "ix_user_identities_user_id" in {index.name for index in identities.indexes}
    assert sa.inspect(User).relationships["identities"].back_populates == "user"


def test_associations_are_v1_anchored_without_client_refs() -> None:
    for table_name, reference in (
        ("user_policies", "policy"),
        ("user_household_associations", "household"),
        ("user_simulation_associations", "simulation"),
        ("user_report_associations", "report"),
    ):
        table = V2_METADATA.tables[table_name]
        assert table.c[f"{reference}_id"].nullable
        assert table.c[f"legacy_{reference}_id"].nullable
        assert isinstance(table.c[f"legacy_{reference}_id"].type, sa.BigInteger)
        assert "client_ref" not in table.c
        assert not table.c.country_id.nullable
        assert table.c.country_id.type.length == 2
        constraints = {constraint.name: constraint for constraint in table.constraints}
        reference_check = constraints[f"ck_{table_name}_{reference}_ref"]
        assert str(reference_check.sqltext) == (
            f"{reference}_id IS NOT NULL OR legacy_{reference}_id IS NOT NULL"
        )
        # No uniqueness involves the owner, so a merge at sign-in can move
        # any association to another user unchanged.
        assert {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        } == {("id", "country_id")}


def test_simulation_and_report_associations_have_no_cross_service_keys() -> None:
    simulations = V2_METADATA.tables["user_simulation_associations"]
    reports = V2_METADATA.tables["user_report_associations"]

    assert {
        foreign_key.target_fullname for foreign_key in simulations.foreign_keys
    } == {"users.id"}
    assert {foreign_key.target_fullname for foreign_key in reports.foreign_keys} == {
        "users.id",
        "user_policies.id",
    }
    user_policy_key = next(iter(reports.c.user_policy_id.foreign_keys))
    assert user_policy_key.ondelete == "SET NULL"
    for column_name in ("provisions", "validation"):
        postgres_type = reports.c[column_name].type.dialect_impl(postgresql.dialect())
        assert isinstance(postgres_type, postgresql.JSONB)
    assert set(sa.inspect(UserSimulationAssociation).relationships.keys()) == {"user"}
    assert set(sa.inspect(UserReportAssociation).relationships.keys()) == {"user"}


def test_user_policy_records_v3_reform_fields() -> None:
    policies = V2_METADATA.tables["user_policies"]

    assert policies.c.baseline.type.length == 16
    baseline_check = next(
        constraint
        for constraint in policies.constraints
        if constraint.name == "ck_user_policies_baseline"
    )
    assert "current-law" in str(baseline_check.sqltext)
    assert "current-policy" in str(baseline_check.sqltext)
    postgres_type = policies.c.provenance.type.dialect_impl(postgresql.dialect())
    assert isinstance(postgres_type, postgresql.JSONB)
