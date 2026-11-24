"""Structural contract tests for the complete reviewed v2 SQLModel schema.

Columns are read from the models' mappers, and keys, constraints and indexes
from SQLite's copy of the schema (tests/unit/v2/v2_schema_reading.py).
"""

from typing import Literal
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlmodel.sql.sqltypes import AutoString

from policyengine_api.data.v1_models import V1Base
from policyengine_api.data.v2.models import (
    V2_METADATA,
    Country,
    DatasetVersion,
    Dynamic,
    Household,
    HouseholdJob,
    LegacyHouseholdMapping,
    LegacyPolicyMapping,
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    ParameterTreeChild,
    ParameterValue,
    Policy,
    Simulation,
    SimulationRun,
    TaxBenefitModelVersion,
    User,
    UserHouseholdAssociation,
    UserIdentity,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
    UserType,
)
from tests.fixtures.database_sessions import v2_schema_statements
from tests.unit.v2.v2_schema_reading import (
    declared_index,
    model_columns,
    stored_v2_schema,
    stored_v2_table,
    v2_mappers,
)

# Every column that names the country a record belongs to. Each references the
# countries table instead of checking a fixed list of country IDs.
COUNTRY_REFERENCE_COLUMNS = (
    ("users", "primary_country"),
    ("households", "country_id"),
    ("policies", "country_id"),
    ("user_household_associations", "country_id"),
    ("user_policies", "country_id"),
    ("user_simulation_associations", "country_id"),
    ("user_report_associations", "country_id"),
)

# Outputs of a report run. Poverty and inequality describe one simulation, so
# they belong to a simulation run instead (test_simulation_run_models.py).
RUN_OUTPUT_TABLES = frozenset(
    {
        "aggregates",
        "budget_summary",
        "change_aggregates",
        "congressional_district_impacts",
        "constituency_impacts",
        "decile_impacts",
        "intra_decile_impacts",
        "local_authority_impacts",
        "program_statistics",
        "withheld_area_codes",
    }
)


def test_domain_models_are_grouped_into_topic_scoped_modules() -> None:
    expected_modules = {
        Country: "countries",
        User: "users",
        UserIdentity: "users",
        Policy: "policies",
        Dynamic: "policies",
        Household: "households",
        HouseholdJob: "households",
        LegacyHouseholdMapping: "household_mappings",
        Simulation: "simulations",
        SimulationRun: "simulations",
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


def test_every_metadata_table_has_one_mapped_model() -> None:
    # SQLite's copy holds every table of V2_METADATA: create_all made it.
    metadata_table_names = set(stored_v2_schema())
    model_table_names = {mapper.class_.__tablename__ for mapper in v2_mappers()}

    assert V2_METADATA is not V1Base.metadata
    assert model_table_names == metadata_table_names
    assert len(v2_mappers()) == len(metadata_table_names)


def test_every_table_has_named_primary_foreign_and_relational_constraints() -> None:
    tables = stored_v2_schema()

    for table in tables.values():
        assert table.primary_key
        assert table.primary_key_name
        for constraint_name in table.constraint_names:
            assert constraint_name, f"unnamed constraint on {table.name}"
        for index_name in table.indexes:
            assert index_name, f"unnamed index on {table.name}"
        for foreign_key in table.foreign_keys:
            assert foreign_key.name
            assert foreign_key.ondelete in {"CASCADE", "RESTRICT", "SET NULL"}
            assert foreign_key.referred_table in tables


def test_every_declared_relationship_has_a_complete_back_populates_pair() -> None:
    configure_mappers()

    for mapper in v2_mappers():
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
        foreign_keys = stored_v2_table(table_name).foreign_keys_of("user_id")
        assert len(foreign_keys) == 1
        assert foreign_keys[0].target == "users.id"
        assert foreign_keys[0].ondelete == "CASCADE"

        association_user = sa.inspect(model).relationships["user"]
        assert association_user.back_populates == user_collection
        assert user_mapper.relationships[user_collection].back_populates == "user"


def test_policy_content_identity_and_catalog_columns_are_explicit() -> None:
    columns = model_columns("policies")
    policies = stored_v2_table("policies")

    assert {"name", "description"}.isdisjoint(columns.keys())
    assert {
        "country_id",
        "tax_benefit_model_id",
        "tax_benefit_model_version_id",
        "canonicalization_version",
        "content_hash",
        "created_at",
        "updated_at",
    }.issubset(columns.keys())
    assert columns.country_id.type.length == 2
    assert columns.content_hash.type.length == 64
    assert ("id", "country_id") in policies.unique_column_sets
    assert ("canonicalization_version", "content_hash") in policies.unique_column_sets
    assert {
        "ix_policies_country_model",
        "ix_policies_country_model_version",
    } <= set(policies.indexes)


def test_policy_parameter_values_use_jsonb_and_enforce_period_identity() -> None:
    columns = model_columns("parameter_values")
    values = stored_v2_table("parameter_values")

    postgres_type = columns.value_json.type.dialect_impl(postgresql.dialect())
    assert isinstance(postgres_type, postgresql.JSONB)
    assert {
        "ck_parameter_values_single_owner",
        "ck_parameter_values_effective_period",
    } <= values.constraint_names
    assert ("policy_id", "parameter_id", "start_date") in values.unique_column_sets
    assert sa.inspect(ParameterValue).relationships["policy"].back_populates == (
        "parameter_values"
    )


def test_user_policy_is_an_independent_country_scoped_association() -> None:
    columns = model_columns("user_policies")
    associations = stored_v2_table("user_policies")

    assert isinstance(columns.user_id.type, sa.Uuid)
    user_foreign_key = associations.foreign_keys_of("user_id")[0]
    assert user_foreign_key.target == "users.id"
    assert user_foreign_key.ondelete == "CASCADE"
    assert {"country", "label"}.isdisjoint(columns.keys())
    assert {"country_id", "name", "description"}.issubset(columns.keys())
    assert columns.name.nullable
    assert columns.description.nullable
    assert ("user_id", "policy_id") not in associations.unique_column_sets
    assert ("id", "country_id") in associations.unique_column_sets
    policy_country = associations.foreign_key_named("fk_user_policies_policy_country")
    assert policy_country.columns == ("policy_id", "country_id")
    assert policy_country.targets == ("policies.id", "policies.country_id")
    assert policy_country.ondelete == "RESTRICT"
    assert sa.inspect(UserPolicy).relationships["user"].back_populates == (
        "policy_associations"
    )


def test_legacy_user_mapping_is_one_to_one() -> None:
    columns = model_columns("legacy_user_mappings")
    mappings = stored_v2_table("legacy_user_mappings")

    assert mappings.primary_key == ("legacy_user_id",)
    assert columns.legacy_user_id.type.length == 255
    assert columns.created_at.type.timezone
    assert ("user_id",) in mappings.unique_column_sets
    user_foreign_key = mappings.foreign_keys_of("user_id")[0]
    assert user_foreign_key.target == "users.id"
    assert user_foreign_key.ondelete == "RESTRICT"


def test_legacy_policy_mapping_is_many_to_one_by_destination() -> None:
    columns = model_columns("legacy_policy_mappings")
    mappings = stored_v2_table("legacy_policy_mappings")

    assert ("country_id", "legacy_policy_id") in mappings.unique_column_sets
    assert ("policy_id",) not in mappings.unique_column_sets
    assert columns.source_policy_hash.type.length == 255
    policy_country = mappings.foreign_key_named(
        "fk_legacy_policy_mappings_policy_country"
    )
    assert policy_country.ondelete == "RESTRICT"
    dynamic_country = mappings.foreign_key_named(
        "fk_legacy_policy_mappings_dynamic_country"
    )
    assert dynamic_country.ondelete == "RESTRICT"


def test_legacy_user_policy_mapping_is_one_to_one_by_destination() -> None:
    columns = model_columns("legacy_user_policy_mappings")
    mappings = stored_v2_table("legacy_user_policy_mappings")

    assert ("country_id", "legacy_user_policy_id") in mappings.unique_column_sets
    assert ("user_policy_id",) in mappings.unique_column_sets
    assert columns.fingerprint_sha256.type.length == 64
    assert columns.last_applied_source_revision.server_default.arg == "0"
    assert "ck_legacy_user_policy_mappings_source_revision" in (
        mappings.constraint_names
    )
    association_country = mappings.foreign_keys[0]
    assert (
        association_country.name == "fk_legacy_user_policy_mappings_association_country"
    )
    assert association_country.ondelete == "CASCADE"


def test_all_datetime_columns_are_timezone_aware() -> None:
    datetime_columns = [
        column
        for mapper in v2_mappers()
        for column in mapper.columns
        if isinstance(column.type, sa.DateTime)
    ]

    assert datetime_columns
    assert all(column.type.timezone for column in datetime_columns)


def test_report_definition_and_run_columns_are_separated() -> None:
    report = model_columns("reports")
    report_run = model_columns("report_runs")

    assert report.type.nullable
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
    }.issubset(report.keys())
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
    }.issubset(report_run.keys())
    assert {
        "country_package_version",
        "policyengine_version",
        "status",
        "error_message",
        "markdown",
    }.isdisjoint(report.keys())
    assert not report_run.country_package_version.nullable
    assert not report_run.policyengine_version.nullable
    assert isinstance(report_run.idempotency_key.type, sa.Uuid)
    assert report_run.idempotency_key.type.as_uuid


def test_standard_users_require_a_supported_primary_country() -> None:
    users = model_columns("users")

    # Nullable only for unauthenticated users; a check requires it otherwise.
    assert users.primary_country.nullable
    assert users.first_name.nullable
    assert users.last_name.nullable
    assert users.email.nullable
    assert users.primary_country.type.length == 2
    # The countries table, not a check, lists the countries a user may choose.
    assert stored_v2_table("users").checks == {
        "ck_users_user_type_allowed": (
            "user_type IN ('unauthenticated', 'standard', 'author', 'admin')"
        ),
        "ck_users_standard_primary_country": (
            "user_type = 'unauthenticated' OR primary_country IS NOT NULL"
        ),
    }


def test_user_type_defaults_to_standard_for_every_writer() -> None:
    users = model_columns("users")

    assert not users.user_type.nullable
    assert users.user_type.type.length == 16
    # The server default covers inserts by Public API revisions that predate
    # the column; the Python default covers this revision's ORM inserts.
    assert users.user_type.server_default.arg == "standard"
    assert User().user_type == "standard"
    assert [member.value for member in UserType] == [
        "unauthenticated",
        "standard",
        "author",
        "admin",
    ]


def test_regions_have_one_same_model_version_default_logical_dataset() -> None:
    regions = model_columns("regions")
    datasets = model_columns("datasets")
    stored_regions = stored_v2_table("regions")
    stored_datasets = stored_v2_table("datasets")

    assert "region_datasets" not in stored_v2_schema()
    assert not regions.default_dataset_id.nullable
    assert regions.default_dataset_id.index
    default_constraint = stored_regions.foreign_key_named(
        "fk_regions_default_dataset_model_version"
    )
    assert default_constraint.columns == (
        "default_dataset_id",
        "tax_benefit_model_version_id",
    )
    assert default_constraint.targets == (
        "datasets.id",
        "datasets.tax_benefit_model_version_id",
    )
    assert default_constraint.ondelete == "RESTRICT"

    unique_column_sets = stored_datasets.unique_column_sets
    assert ("tax_benefit_model_version_id", "name") in unique_column_sets
    assert ("id", "tax_benefit_model_version_id") in unique_column_sets
    assert "tax_benefit_model_id" not in datasets
    assert "tax_benefit_model_id" not in regions
    assert not datasets.tax_benefit_model_version_id.nullable
    assert not regions.tax_benefit_model_version_id.nullable
    assert datasets.storage_path.nullable
    assert "ck_datasets_output_storage_path" in stored_datasets.constraint_names


def test_reports_and_simulations_snapshot_selected_datasets() -> None:
    for table_name in ("reports", "simulations"):
        table = stored_v2_table(table_name)
        dataset_foreign_key = table.foreign_keys_of("dataset_id")[0]
        assert dataset_foreign_key.target == "datasets.id"
        assert dataset_foreign_key.ondelete in {"RESTRICT", "SET NULL"}


def test_stage9_adds_no_dataset_version_relationship_to_run_tables() -> None:
    for table_name in ("simulations", "reports", "report_runs"):
        assert "dataset_version_id" not in model_columns(table_name)


def test_run_outputs_reference_report_runs_not_base_reports() -> None:
    for table_name in RUN_OUTPUT_TABLES:
        columns = model_columns(table_name)
        assert "report_run_id" in columns
        assert not columns.report_run_id.nullable
        assert "report_id" not in columns
        foreign_key = stored_v2_table(table_name).foreign_keys_of("report_run_id")[0]
        assert foreign_key.target == "report_runs.id"
        assert foreign_key.ondelete == "CASCADE"


def test_uk_area_impacts_store_no_map_coordinates() -> None:
    for table_name in ("constituency_impacts", "local_authority_impacts"):
        assert {"x", "y"}.isdisjoint(model_columns(table_name).keys())


def test_report_reruns_deduplicate_requests_and_keep_failed_or_forced_runs() -> None:
    """A report's versions are unique only among runs that neither failed nor forced.

    A failed run never counts and a forced re-run is an extra run, so no plain
    constraint covers the versions; ``test_shared_report_models.py`` checks the
    partial unique index that does.
    """
    report_runs = stored_v2_table("report_runs")
    unique_column_sets = report_runs.unique_column_sets

    assert ("report_id", "idempotency_key") in unique_column_sets
    assert (
        "report_id",
        "country_package_version",
        "policyengine_version",
    ) not in unique_column_sets
    assert {
        "ix_report_runs_current_output",
        "uq_report_runs_unfailed_unforced_versions",
    } <= set(report_runs.indexes)


def test_named_checks_and_required_indexes_cover_core_invariants() -> None:
    tables = stored_v2_schema().values()
    constraint_names = {
        constraint_name
        for table in tables
        for constraint_name in table.constraint_names
    }
    index_names = {index_name for table in tables for index_name in table.indexes}

    assert {
        "ck_regions_required_filter_values",
        "ck_simulations_type_input",
        "ck_users_standard_primary_country",
        "ck_countries_society_wide_requires_household",
        "ck_report_runs_terminal_completion",
        "ck_simulation_runs_terminal_completion",
        "ck_parameter_values_single_owner",
    }.issubset(constraint_names)
    assert {
        "ix_users_email",
        "ix_simulation_runs_current_output",
        "ix_report_runs_current_output",
        "uq_parameter_values_canonical_parameter_start_date",
    }.issubset(index_names)


def test_stage9_uses_policyengine_version_as_its_only_catalog_release_identity() -> (
    None
):
    model_version = model_columns(TaxBenefitModelVersion)
    dataset_version = model_columns(DatasetVersion)
    forbidden_columns = {
        "policyengine_version",
        "core_version",
        "country_package_version",
        "dataset_release",
        "dataset_digest",
        "catalog_fingerprint",
    }

    assert set(model_version) >= {
        model_version.model_id,
        model_version.version,
        model_version.current_law_id,
        model_version.metadata_time_periods,
    }
    assert forbidden_columns.isdisjoint(model_version.keys())
    assert forbidden_columns.isdisjoint(dataset_version.keys())

    unique_column_sets = stored_v2_table(
        TaxBenefitModelVersion.__tablename__
    ).unique_column_sets
    assert ("model_id", "version") in unique_column_sets


def test_canonical_parameter_values_have_a_postgres_partial_unique_index() -> None:
    index = declared_index(
        ParameterValue, "uq_parameter_values_canonical_parameter_start_date"
    )

    assert index.unique
    assert tuple(column.name for column in index.columns) == (
        "parameter_id",
        "start_date",
    )
    predicate = str(index.dialect_options["postgresql"]["where"])
    assert predicate == "policy_id IS NULL AND dynamic_id IS NULL"


def test_complete_metadata_compiles_for_postgres_without_mutation() -> None:
    statements = [
        statement
        for statement in v2_schema_statements("postgresql")
        if statement.lstrip().startswith("CREATE TABLE")
    ]

    # One CREATE TABLE for each table of V2_METADATA, which SQLite's copy holds.
    assert len(statements) == len(stored_v2_schema())


def test_user_identity_maps_one_issuer_subject_to_one_user() -> None:
    identities = model_columns("user_identities")
    stored_identities = stored_v2_table("user_identities")

    assert stored_identities.unique_constraints == {
        "uq_user_identities_issuer_subject": ("issuer", "subject")
    }
    assert isinstance(identities.issuer.type, sa.Text)
    assert isinstance(identities.subject.type, sa.Text)
    assert identities.email.nullable
    assert identities.email.type.length == 320
    assert not identities.last_seen_at.nullable
    user_foreign_key = stored_identities.foreign_keys_of("user_id")[0]
    assert user_foreign_key.target == "users.id"
    assert user_foreign_key.ondelete == "CASCADE"
    assert "ix_user_identities_user_id" in stored_identities.indexes
    assert sa.inspect(User).relationships["identities"].back_populates == "user"


def test_associations_are_v1_anchored_without_client_refs() -> None:
    for table_name, reference in (
        ("user_policies", "policy"),
        ("user_household_associations", "household"),
        ("user_simulation_associations", "simulation"),
        ("user_report_associations", "report"),
    ):
        columns = model_columns(table_name)
        table = stored_v2_table(table_name)
        assert columns[f"{reference}_id"].nullable
        assert columns[f"legacy_{reference}_id"].nullable
        assert isinstance(columns[f"legacy_{reference}_id"].type, sa.BigInteger)
        assert "client_ref" not in columns
        assert not columns.country_id.nullable
        assert columns.country_id.type.length == 2
        reference_check = table.checks[f"ck_{table_name}_{reference}_ref"]
        assert reference_check == (
            f"{reference}_id IS NOT NULL OR legacy_{reference}_id IS NOT NULL"
        )
        # No uniqueness involves the owner, so a merge at sign-in can move
        # any association to another user unchanged.
        assert table.unique_column_sets == {("id", "country_id")}


def test_saved_simulations_and_reports_name_stored_v2_rows() -> None:
    """A saved simulation or report names a stored simulation or report.

    ``simulation_id`` and ``report_id`` are foreign keys to ``simulations`` and
    ``reports``, with ``RESTRICT``: a saved item can't name a row that doesn't
    exist, and a simulation or report a saved item names can't be deleted.
    """
    simulations = stored_v2_table("user_simulation_associations")
    reports = stored_v2_table("user_report_associations")
    report_columns = model_columns("user_report_associations")

    # The retired columns stay, nullable, for the previous Public API revision.
    for table_name in ("user_simulation_associations", "user_report_associations"):
        columns = model_columns(table_name)
        assert columns.country.nullable
        assert columns.label.nullable
    assert {foreign_key.target for foreign_key in simulations.foreign_key_columns} == {
        "users.id",
        "countries.id",
        "simulations.id",
    }
    assert {foreign_key.target for foreign_key in reports.foreign_key_columns} == {
        "users.id",
        "user_policies.id",
        "countries.id",
        "reports.id",
    }
    simulation_key = simulations.foreign_key("simulation_id")
    assert simulation_key.target == "simulations.id"
    assert simulation_key.ondelete == "RESTRICT"
    report_key = reports.foreign_key("report_id")
    assert report_key.target == "reports.id"
    assert report_key.ondelete == "RESTRICT"
    user_policy_key = reports.foreign_keys_of("user_policy_id")[0]
    assert user_policy_key.ondelete == "SET NULL"
    for column_name in ("provisions", "validation"):
        column_type = report_columns[column_name].type
        postgres_type = column_type.dialect_impl(postgresql.dialect())
        assert isinstance(postgres_type, postgresql.JSONB)
    assert set(sa.inspect(UserSimulationAssociation).relationships.keys()) == {"user"}
    assert set(sa.inspect(UserReportAssociation).relationships.keys()) == {"user"}
    assert "user_associations" not in sa.inspect(Simulation).relationships


def test_user_policy_records_v3_reform_fields() -> None:
    policies = model_columns("user_policies")

    assert policies.baseline.type.length == 16
    baseline_check = stored_v2_table("user_policies").checks[
        "ck_user_policies_baseline"
    ]
    assert "current-law" in baseline_check
    assert "current-policy" in baseline_check
    postgres_type = policies.provenance.type.dialect_impl(postgresql.dialect())
    assert isinstance(postgres_type, postgresql.JSONB)


def test_countries_record_household_and_society_wide_capability() -> None:
    countries = model_columns("countries")
    stored_countries = stored_v2_table("countries")

    assert countries.keys() == ["id", "household_enabled", "society_wide_enabled"]
    assert stored_countries.primary_key == ("id",)
    assert stored_countries.primary_key_name == "pk_countries"
    assert countries.id.type.length == 2
    for flag_name in ("household_enabled", "society_wide_enabled"):
        assert isinstance(countries[flag_name].type, sa.Boolean)
        assert not countries[flag_name].nullable
        assert countries[flag_name].server_default is None
    # Society-wide reports need household calculations, so a society-wide
    # country is always household capable too.
    assert stored_countries.checks == {
        "ck_countries_society_wide_requires_household": (
            "household_enabled OR NOT society_wide_enabled"
        ),
    }


def test_country_columns_reference_the_countries_table_instead_of_a_fixed_list() -> (
    None
):
    for table_name, column_name in COUNTRY_REFERENCE_COLUMNS:
        table = stored_v2_table(table_name)
        country_keys = [
            foreign_key
            for foreign_key in table.foreign_keys_of(column_name)
            if foreign_key.referred_table == "countries"
        ]
        assert len(country_keys) == 1, table_name
        assert country_keys[0].target == "countries.id"
        assert country_keys[0].ondelete == "RESTRICT"
        assert country_keys[0].constraint_name == (
            f"fk_{table_name}_{column_name}_countries"
        )
        fixed_country_checks = [
            check_name
            for check_name, condition in table.checks.items()
            if "'us', 'uk'" in condition
        ]
        assert fixed_country_checks == [], table_name


def test_v1_copy_mappings_keep_their_us_and_uk_checks() -> None:
    # These tables pair v1 records with their v2 copies. Each already
    # references a v2 record of the same country, and they are removed with
    # dual-write, so they keep their fixed checks.
    for table_name in (
        "legacy_household_mappings",
        "legacy_policy_mappings",
        "legacy_user_policy_mappings",
    ):
        table = stored_v2_table(table_name)
        assert f"ck_{table_name}_country" in table.constraint_names
        assert "countries.id" not in {
            foreign_key.target for foreign_key in table.foreign_key_columns
        }


def test_spm_availability_is_nullable_for_versions_not_yet_recorded() -> None:
    """Publication records it after the catalog, so a version may lack it."""
    column = model_columns("tax_benefit_model_versions")["spm_availability"]

    assert column.nullable
    assert column.server_default is None
    assert isinstance(column.type, sa.JSON)


def test_catalog_format_2_columns_are_nullable_for_earlier_versions() -> None:
    """Catalog format 2 stores v3's metadata; versions published before it keep null.

    The model version records its catalog format, entities and basic inputs; each
    variable its input flags, module, parameter-named parts and enum labels; each
    parameter its economy and household flags.
    """
    expected_columns = {
        "tax_benefit_model_versions": {
            "catalog_format": sa.Integer,
            "entities": sa.JSON,
            "basic_inputs": sa.JSON,
        },
        "variables": {
            "is_input_variable": sa.Boolean,
            "hidden_input": sa.Boolean,
            "module_name": AutoString,
            "adds_parameter_path": AutoString,
            "subtracts_parameter_path": AutoString,
            "enum_values": sa.JSON,
            "unit": AutoString,
            "definition_period": AutoString,
        },
        "parameters": {
            "economy": sa.Boolean,
            "household": sa.Boolean,
        },
    }

    for table_name, columns in expected_columns.items():
        mapped_columns = model_columns(table_name)
        for column_name, column_type in columns.items():
            column = mapped_columns[column_name]
            assert column.nullable, f"{table_name}.{column_name}"
            assert column.server_default is None, f"{table_name}.{column_name}"
            assert isinstance(column.type, column_type), f"{table_name}.{column_name}"

    variables = model_columns("variables")
    for column_name in (
        "module_name",
        "adds_parameter_path",
        "subtracts_parameter_path",
    ):
        assert variables[column_name].type.length == 512
    assert variables["unit"].type.length == 128
    assert variables["definition_period"].type.length == 32


def test_catalog_format_2_json_columns_have_typed_shapes() -> None:
    """The entity and enum-value columns name typed shapes the catalog records match.

    Readers of these columns get the keys and value types without re-checking.
    """
    from typing import get_type_hints

    from policyengine_api.data.v2.catalog.records import EntityRecord, EnumValueRecord
    from policyengine_api.data.v2.models import (
        CatalogEntity,
        CatalogEnumValue,
        Variable,
    )

    assert TaxBenefitModelVersion.model_fields["entities"].annotation == (
        list[CatalogEntity] | None
    )
    assert Variable.model_fields["enum_values"].annotation == (
        list[CatalogEnumValue] | None
    )
    for typed_shape, record in (
        (CatalogEntity, EntityRecord),
        (CatalogEnumValue, EnumValueRecord),
    ):
        assert get_type_hints(typed_shape) == get_type_hints(record)


def test_parameter_tree_children_have_one_row_per_path_in_listing_order() -> None:
    """Each version's tree rows are unique by path and listed per parent by index.

    The full listing and the listing of what a reform can change each read one
    unique index (version, parent path, position); a parameter row references
    its parameter, and both references are removed with their rows.
    """
    columns = model_columns("parameter_tree_children")
    table = stored_v2_table("parameter_tree_children")

    assert set(columns.keys()) == {
        "id",
        "created_at",
        "tax_benefit_model_version_id",
        "parent_path",
        "path",
        "position",
        "label",
        "child_type",
        "child_count",
        "reform_position",
        "reform_child_count",
        "parameter_id",
        "economy",
        "household",
    }
    for column_name in ("parent_path", "path", "label"):
        assert columns[column_name].type.length == 512
        assert not columns[column_name].nullable
    for column_name in (
        "child_count",
        "reform_position",
        "reform_child_count",
        "parameter_id",
        "economy",
        "household",
    ):
        assert columns[column_name].nullable
    assert ("tax_benefit_model_version_id", "path") in table.unique_column_sets
    indexes = {
        index_name: (index.columns, index.unique)
        for index_name, index in table.indexes.items()
    }
    assert indexes["ix_parameter_tree_children_listing"] == (
        ("tax_benefit_model_version_id", "parent_path", "position"),
        True,
    )
    assert indexes["ix_parameter_tree_children_reform_listing"] == (
        ("tax_benefit_model_version_id", "parent_path", "reform_position"),
        True,
    )
    assert indexes["ix_parameter_tree_children_parameter_id"] == (
        ("parameter_id",),
        False,
    )
    assert table.references_by_column == {
        "tax_benefit_model_version_id": ("tax_benefit_model_versions", "CASCADE"),
        "parameter_id": ("parameters", "CASCADE"),
    }
    assert set(table.checks) == {
        "ck_parameter_tree_children_child_type",
        "ck_parameter_tree_children_parameter_reference",
    }


def test_parameter_tree_child_type_is_typed_with_its_two_values() -> None:
    """Reads of a tree row keep the child type's two values as a type."""
    annotation = ParameterTreeChild.model_fields["child_type"].annotation

    assert annotation == Literal["node", "parameter"]
    column = model_columns("parameter_tree_children")["child_type"]
    assert isinstance(column.type, AutoString)
    assert column.type.length == 16


def test_parameter_search_files_hold_one_compressed_file_per_version() -> None:
    """Each catalog version has one search file per format, removed with it.

    The row holds the gzip-compressed JSON, its file format, the SHA-256 of the
    uncompressed JSON (the response's ETag) and both sizes.
    """
    columns = model_columns("parameter_search_files")
    table = stored_v2_table("parameter_search_files")

    assert set(columns.keys()) == {
        "id",
        "created_at",
        "tax_benefit_model_version_id",
        "file_format",
        "compressed_content",
        "content_sha256",
        "uncompressed_size",
        "compressed_size",
    }
    for column in columns:
        assert not column.nullable, column.name
    assert isinstance(columns["compressed_content"].type, sa.LargeBinary)
    assert columns["content_sha256"].type.length == 64
    assert table.unique_constraints == {
        "uq_parameter_search_files_model_version_format": (
            "tax_benefit_model_version_id",
            "file_format",
        )
    }
    assert table.references_by_column == {
        "tax_benefit_model_version_id": ("tax_benefit_model_versions", "CASCADE"),
    }


def test_catalog_pruning_marker_is_a_nullable_timezone_aware_timestamp() -> None:
    """A model version records when catalog publication pruned its values.

    The column is null for a version whose current-law values, parameter tree
    and search file are stored, and holds the time pruning removed them. It
    has no default, so a version is published unpruned.
    """
    column = model_columns("tax_benefit_model_versions")["catalog_values_pruned_at"]

    assert column.nullable
    assert column.server_default is None
    assert column.default is None
    assert isinstance(column.type, sa.DateTime)
    assert column.type.timezone is True
    unpruned_version = TaxBenefitModelVersion(
        model_id=uuid4(),
        version="5.0.1",
        current_law_id=2,
        metadata_time_periods=[2026],
    )
    assert unpruned_version.catalog_values_pruned_at is None


def test_catalog_publication_time_is_a_nullable_timezone_aware_timestamp() -> None:
    """A model version records when catalog publication last published it.

    Every publication sets it for the versions it publishes; catalog pruning
    keeps the most recently published versions. It is null for a version no
    publication has recorded since the column was added, and has no default.
    """
    column = model_columns("tax_benefit_model_versions")["catalog_last_published_at"]

    assert column.nullable
    assert column.server_default is None
    assert column.default is None
    assert isinstance(column.type, sa.DateTime)
    assert column.type.timezone is True


def test_user_type_changes_record_each_change_of_a_signed_in_users_type() -> None:
    changes = model_columns("user_type_changes")
    stored_changes = stored_v2_table("user_type_changes")

    assert set(changes.keys()) == {
        "id",
        "created_at",
        "user_id",
        "changed_by_user_id",
        "previous_user_type",
        "new_user_type",
        "source",
        "dismissed_at",
    }
    assert not changes.user_id.nullable
    assert changes.changed_by_user_id.nullable
    # Set when the user dismisses the app's notice of the change.
    assert changes.dismissed_at.nullable
    assert isinstance(changes.dismissed_at.type, sa.DateTime)
    assert changes.dismissed_at.type.timezone is True
    # A user's history goes with the user; an admin's deletion keeps the change.
    assert stored_changes.references_by_column == {
        "user_id": ("users", "CASCADE"),
        "changed_by_user_id": ("users", "SET NULL"),
    }
    signed_in_types = "('standard', 'author', 'admin')"
    assert stored_changes.checks == {
        "ck_user_type_changes_previous_user_type": (
            f"previous_user_type IN {signed_in_types}"
        ),
        "ck_user_type_changes_new_user_type": f"new_user_type IN {signed_in_types}",
        "ck_user_type_changes_changed_type": "previous_user_type <> new_user_type",
        # Renamed when invitation was allowed: Alembic compares checks by
        # name only, so a new name makes autogenerate replace the check.
        "ck_user_type_changes_source_allowed": (
            "source IN ('admin_route', 'script', 'invitation')"
        ),
    }
    # The admin's index serves the SET NULL that each user deletion runs.
    assert set(stored_changes.index_columns.values()) == {
        ("user_id", "created_at"),
        ("changed_by_user_id",),
    }


def test_user_invitations_hold_each_invitation_and_only_its_token_hash() -> None:
    invitations = model_columns("user_invitations")
    stored_invitations = stored_v2_table("user_invitations")

    assert set(invitations.keys()) == {
        "id",
        "created_at",
        "email",
        "user_type",
        "token_hash",
        "invited_by_user_id",
        "expires_at",
        "last_sent_at",
        "last_send_error",
        "accepted_at",
        "accepted_by_user_id",
        "revoked_at",
    }
    required = {"id", "created_at", "email", "user_type", "token_hash", "expires_at"}
    assert {column.name for column in invitations if not column.nullable} == required
    for name in ("expires_at", "last_sent_at", "accepted_at", "revoked_at"):
        column_type = invitations[name].type
        assert isinstance(column_type, sa.DateTime), name
        assert column_type.timezone is True, name
    assert invitations.email.type.length == 320
    # A SHA-256 digest in hexadecimal; the token itself is never stored.
    assert invitations.token_hash.type.length == 64
    assert invitations.last_send_error.type.length == 64
    # Deleting the inviting admin keeps the invitation; deleting the user who
    # accepted it deletes it, so the address, theirs, goes with the account.
    assert stored_invitations.references_by_column == {
        "invited_by_user_id": ("users", "SET NULL"),
        "accepted_by_user_id": ("users", "CASCADE"),
    }
    assert stored_invitations.checks == {
        "ck_user_invitations_user_type": "user_type IN ('author', 'admin')",
        "ck_user_invitations_accepted_or_revoked": (
            "accepted_at IS NULL OR revoked_at IS NULL"
        ),
    }
    assert stored_invitations.unique_column_sets == {("token_hash",)}
    # The users' indexes serve what each user deletion runs on them.
    assert set(stored_invitations.index_columns.values()) == {
        ("invited_by_user_id",),
        ("accepted_by_user_id",),
    }
