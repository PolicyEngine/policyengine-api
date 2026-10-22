"""Exercise the isolated v2 Alembic lifecycle against disposable Postgres."""

import itertools
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.dialects import postgresql

from policyengine_api.constants import REPO
from policyengine_api.data.v2.metadata_validation import SIMULATION_SERVICE_TABLES
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    V2_ALEMBIC_HEAD_REVISION,
    V2MigrationTargetError,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL

BASELINE_REVISION = "f5ef4347cb2a"
STAGE_11_PREVIOUS_REVISION = "af34023a728f"
STAGE_12_PREVIOUS_REVISION = "724b1b11a33e"
STAGE_12_COMPARISON_PREVIOUS_REVISION = "439303be14fe"
STAGE_12A_PREVIOUS_REVISION = "91af4fc8d8c1"
SIMULATION_TABLE_REMOVAL_REVISION = "363f34954a14"
V2_TABLE_NAMES = frozenset(table.name for table in V2_METADATA.tables.values())
# The retired association columns the removal revision drops.
RETIRED_ASSOCIATION_COLUMNS = {
    "user_simulation_associations": frozenset({"country", "label"}),
    "user_report_associations": frozenset({"country", "label"}),
}
# The native enum types only the dropped tables used.
SIMULATION_DOMAIN_ENUM_TYPES = frozenset(
    {
        "v2_aggregate_type",
        "v2_decile_type",
        "v2_household_job_status",
        "v2_output_status",
        "v2_report_run_status",
        "v2_report_run_trigger",
        "v2_simulation_status",
        "v2_simulation_type",
    }
)


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(V2_ALEMBIC_DISPOSABLE_TEST, ""),
        }
    )
    if not settings.disposable_test:
        pytest.fail("v2 lifecycle tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


def _config() -> Config:
    return Config(str(REPO / "alembic-v2.ini"))


def _simulation_table_removal_parent() -> str:
    """Return the revision the simulation-table removal applies to."""
    removal = ScriptDirectory.from_config(_config()).get_revision(
        SIMULATION_TABLE_REMOVAL_REVISION
    )
    return removal.down_revision


def _assert_head(engine) -> None:
    assert set(inspect(engine).get_table_names(schema="public")) == (
        V2_TABLE_NAMES | {"alembic_version"}
    )
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert context.get_current_revision() == V2_ALEMBIC_HEAD_REVISION
        assert compare_metadata(context, V2_METADATA) == []
        model_count = connection.execute(
            text(
                "SELECT count(*) FROM public.tax_benefit_models "
                "WHERE name = 'stage8-platform-validation'"
            )
        ).scalar_one()
        version_count = connection.execute(
            text(
                "SELECT count(*) FROM public.tax_benefit_model_versions "
                "WHERE version = 'stage8-platform-validation'"
            )
        ).scalar_one()
    assert (model_count, version_count) == (0, 0)
    parameter_value_indexes = {
        index["name"]: index
        for index in inspect(engine).get_indexes("parameter_values")
    }
    canonical_index = parameter_value_indexes[
        "uq_parameter_values_canonical_parameter_start_date"
    ]
    assert canonical_index["unique"]
    assert canonical_index["column_names"] == ["parameter_id", "start_date"]
    policy_value_constraint = next(
        constraint
        for constraint in inspect(engine).get_unique_constraints("parameter_values")
        if constraint["name"] == "uq_parameter_values_policy_parameter_start_date"
    )
    assert policy_value_constraint["column_names"] == [
        "policy_id",
        "parameter_id",
        "start_date",
    ]
    assert {
        "legacy_household_mappings",
        "legacy_policy_mappings",
        "legacy_user_mappings",
        "legacy_user_policy_mappings",
    } <= set(inspect(engine).get_table_names(schema="public"))


def _columns(engine, table_name: str) -> dict[str, dict]:
    return {
        column["name"]: column
        for column in inspect(engine).get_columns(table_name, schema="public")
    }


def _assert_pre_stage_12a_association_shape(engine) -> None:
    assert "user_identities" not in inspect(engine).get_table_names(schema="public")
    for table_name, reference in (
        ("user_simulation_associations", "simulation"),
        ("user_report_associations", "report"),
    ):
        columns = _columns(engine, table_name)
        assert {"country", "label"} <= columns.keys()
        assert {
            "country_id",
            "name",
            f"legacy_{reference}_id",
        }.isdisjoint(columns)
        assert not columns[f"{reference}_id"]["nullable"]
        assert {
            foreign_key["referred_table"]
            for foreign_key in inspect(engine).get_foreign_keys(table_name)
        } == {"users", f"{reference}s"}
    for table_name, reference in (
        ("user_policies", "policy"),
        ("user_household_associations", "household"),
    ):
        columns = _columns(engine, table_name)
        assert f"legacy_{reference}_id" not in columns
        assert not columns[f"{reference}_id"]["nullable"]
    user_columns = _columns(engine, "users")
    assert "user_type" not in user_columns
    assert not user_columns["primary_country"]["nullable"]


def _assert_stage_12a_association_shape(engine) -> None:
    identity_constraints = {
        constraint["name"]: constraint["column_names"]
        for constraint in inspect(engine).get_unique_constraints("user_identities")
    }
    assert identity_constraints["uq_user_identities_issuer_subject"] == [
        "issuer",
        "subject",
    ]
    for table_name, reference in (
        ("user_policies", "policy"),
        ("user_household_associations", "household"),
        ("user_simulation_associations", "simulation"),
        ("user_report_associations", "report"),
    ):
        columns = _columns(engine, table_name)
        assert columns[f"{reference}_id"]["nullable"]
        assert columns[f"legacy_{reference}_id"]["nullable"]
        assert not columns["country_id"]["nullable"]
        assert "client_ref" not in columns
        # No uniqueness involves the owner, so a merge can move any row.
        assert [
            constraint["column_names"]
            for constraint in inspect(engine).get_unique_constraints(table_name)
        ] == [["id", "country_id"]]
    for table_name in ("user_simulation_associations", "user_report_associations"):
        referred_tables = {
            foreign_key["referred_table"]
            for foreign_key in inspect(engine).get_foreign_keys(table_name)
        }
        assert {"simulations", "reports"}.isdisjoint(referred_tables)
    report_policy_key = next(
        foreign_key
        for foreign_key in inspect(engine).get_foreign_keys("user_report_associations")
        if foreign_key["referred_table"] == "user_policies"
    )
    assert report_policy_key["options"]["ondelete"] == "SET NULL"
    user_columns = _columns(engine, "users")
    assert not user_columns["user_type"]["nullable"]
    assert "standard" in user_columns["user_type"]["default"]
    assert user_columns["primary_country"]["nullable"]
    user_checks = {
        constraint["name"]
        for constraint in inspect(engine).get_check_constraints("users")
    }
    assert {
        "ck_users_primary_country",
        "ck_users_user_type",
        "ck_users_standard_primary_country",
    } <= user_checks


def _enum_type_names(engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text("SELECT typname FROM pg_type WHERE typtype = 'e'")
            ).scalars()
        )


def _assert_simulation_domain_schema_present(engine) -> None:
    assert set(inspect(engine).get_table_names(schema="public")) >= (
        SIMULATION_SERVICE_TABLES
    )
    assert _enum_type_names(engine) >= SIMULATION_DOMAIN_ENUM_TYPES
    for table_name, retired_columns in RETIRED_ASSOCIATION_COLUMNS.items():
        columns = _columns(engine, table_name)
        assert retired_columns <= columns.keys()
        assert all(columns[name]["nullable"] for name in retired_columns)
    filter_pair = next(
        constraint
        for constraint in inspect(engine).get_check_constraints("simulations")
        if constraint["name"] == "ck_simulations_filter_pair"
    )
    assert "filter_field IS NULL" in filter_pair["sqltext"]
    assert "filter_value IS NULL" in filter_pair["sqltext"]


def _assert_simulation_domain_schema_removed(engine) -> None:
    assert SIMULATION_SERVICE_TABLES.isdisjoint(
        inspect(engine).get_table_names(schema="public")
    )
    assert SIMULATION_DOMAIN_ENUM_TYPES.isdisjoint(_enum_type_names(engine))
    for table_name, retired_columns in RETIRED_ASSOCIATION_COLUMNS.items():
        assert retired_columns.isdisjoint(_columns(engine, table_name))


def _upgrade_and_assert_head(config: Config, engine: Engine) -> None:
    command.upgrade(config, "head")
    command.check(config)
    _assert_head(engine)


def _assert_revision(engine: Engine, revision: str) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert context.get_current_revision() == revision


def _assert_revision_without_enum_types(
    engine: Engine, revision: str | None, enum_query: str
) -> None:
    """Check the database revision, then that ``enum_query`` counts no enum types."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert context.get_current_revision() == revision
        enum_count = connection.execute(text(enum_query)).scalar_one()
    assert enum_count == 0


def _insert_legacy_stage12_report(engine: Engine) -> UUID:
    """Store a report from before the comparison columns existed; return its id."""
    legacy_report_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO stage12_evaluation_reports "
                "(evaluation_id, contract_version, status, aggregation_status, "
                "environment, calculation_flow, originating_request_id, "
                "production_identity, worker_version, modal_application, "
                "report_coordinator_callable, version_manifest_sha256, "
                "policyengine_version, country_package_name, "
                "country_package_version, country, dataset_identity, dataset_uri, "
                "data_package_name, data_package_version, data_artifact_revision, "
                "retention_expires_at) VALUES "
                "(:evaluation_id, 1, 'pending', 'not_started', 'test', "
                "'economy', 'request', 'production', '5.2.0', 'application', "
                "'coordinate_report', :digest, '5.2.0', 'policyengine-us', "
                "'1.0.0', 'us', 'dataset', 'hf://dataset/file@revision', "
                "'data-package', '1.0.0', 'revision', now() + interval '1 day')"
            ),
            {"evaluation_id": legacy_report_id, "digest": "a" * 64},
        )
    return legacy_report_id


def _assert_comparison_downgrade_then_store_legacy_report(engine: Engine) -> UUID:
    """Check the comparison revision is gone, then store a pre-comparison report."""
    _assert_revision_without_enum_types(
        engine,
        STAGE_12_COMPARISON_PREVIOUS_REVISION,
        "SELECT count(*) FROM pg_type "
        "WHERE typname = 'v2_stage12_result_comparison_status' "
        "AND typtype = 'e'",
    )
    report_columns = {
        column["name"]
        for column in inspect(engine).get_columns(
            "stage12_evaluation_reports",
            schema="public",
        )
    }
    assert not any(name.startswith("comparison_") for name in report_columns)
    return _insert_legacy_stage12_report(engine)


def _assert_legacy_report_is_not_compared(
    engine: Engine, legacy_report_id: UUID
) -> None:
    with engine.connect() as connection:
        comparison_status = connection.execute(
            text(
                "SELECT comparison_status FROM stage12_evaluation_reports "
                "WHERE evaluation_id = :evaluation_id"
            ),
            {"evaluation_id": legacy_report_id},
        ).scalar_one()
    assert comparison_status == "not_requested"


def _assert_stage12_downgrade(engine: Engine) -> None:
    _assert_revision_without_enum_types(
        engine,
        STAGE_12_PREVIOUS_REVISION,
        "SELECT count(*) FROM pg_type "
        "WHERE typname LIKE 'v2_stage12_%' AND typtype = 'e'",
    )
    assert {
        "stage12_evaluation_reports",
        "stage12_evaluation_simulations",
    }.isdisjoint(inspect(engine).get_table_names(schema="public"))


def _assert_stage11_downgrade(engine: Engine) -> None:
    _assert_revision(engine, STAGE_11_PREVIOUS_REVISION)
    assert "legacy_household_mappings" not in inspect(engine).get_table_names(
        schema="public"
    )
    household_columns = {
        column["name"]: column
        for column in inspect(engine).get_columns(
            "households",
            schema="public",
        )
    }
    assert {"country", "label", "year"} <= household_columns.keys()
    assert {
        "country_id",
        "default_year",
        "canonicalization_version",
        "content_hash",
    }.isdisjoint(household_columns)
    association_columns = {
        column["name"]: column
        for column in inspect(engine).get_columns(
            "user_household_associations",
            schema="public",
        )
    }
    assert {"country", "label"} <= association_columns.keys()
    assert {"country_id", "name", "description"}.isdisjoint(association_columns)
    user_policy_id = next(
        column
        for column in inspect(engine).get_columns(
            "user_policies",
            schema="public",
        )
        if column["name"] == "user_id"
    )
    assert isinstance(user_policy_id["type"], postgresql.UUID)
    user_columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("users", schema="public")
    }
    assert all(
        user_columns[field_name]["nullable"]
        for field_name in ("first_name", "last_name", "email")
    )


def _assert_baseline_downgrade(engine: Engine) -> None:
    _assert_revision(engine, BASELINE_REVISION)
    assert "uq_parameter_values_canonical_parameter_start_date" not in {
        index["name"] for index in inspect(engine).get_indexes("parameter_values")
    }


def _assert_base(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names(schema="public")) <= {"alembic_version"}
    _assert_revision_without_enum_types(
        engine,
        None,
        "SELECT count(*) FROM pg_type WHERE typname LIKE 'v2_%' AND typtype = 'e'",
    )


def test_empty_upgrade_check_base_downgrade_and_reupgrade() -> None:
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names(schema="public")) <= {
            "alembic_version"
        }

        _upgrade_and_assert_head(config, engine)
        _assert_simulation_domain_schema_removed(engine)

        command.downgrade(config, _simulation_table_removal_parent())
        _assert_revision(engine, _simulation_table_removal_parent())
        _assert_simulation_domain_schema_present(engine)
        _upgrade_and_assert_head(config, engine)
        _assert_simulation_domain_schema_removed(engine)

        command.downgrade(config, STAGE_12A_PREVIOUS_REVISION)
        _assert_revision(engine, STAGE_12A_PREVIOUS_REVISION)
        _assert_pre_stage_12a_association_shape(engine)
        _upgrade_and_assert_head(config, engine)
        _assert_stage_12a_association_shape(engine)

        command.downgrade(config, STAGE_12_COMPARISON_PREVIOUS_REVISION)
        legacy_report_id = _assert_comparison_downgrade_then_store_legacy_report(engine)
        _upgrade_and_assert_head(config, engine)
        _assert_legacy_report_is_not_compared(engine, legacy_report_id)

        command.downgrade(config, STAGE_12_PREVIOUS_REVISION)
        _assert_stage12_downgrade(engine)
        _upgrade_and_assert_head(config, engine)

        command.downgrade(config, STAGE_11_PREVIOUS_REVISION)
        _assert_stage11_downgrade(engine)
        _upgrade_and_assert_head(config, engine)

        command.downgrade(config, BASELINE_REVISION)
        _assert_baseline_downgrade(engine)
        _upgrade_and_assert_head(config, engine)

        command.downgrade(config, "base")
        _assert_base(engine)
        _upgrade_and_assert_head(config, engine)
    finally:
        command.upgrade(config, "head")
        engine.dispose()


@dataclass(frozen=True)
class PreviousRevisionUsage:
    """How a previous application revision uses the tables it maps.

    ``read_only_tables`` are tables it maps but never writes, which the newer
    schema may therefore give a new required column; only newer code writes
    their rows. ``nullable_columns_required_by_checks`` are nullable columns
    that one of its check constraints requires a value for.
    """

    read_only_tables: frozenset[str]
    nullable_columns_required_by_checks: frozenset[tuple[str, str]]


# The revision before Stage 12A. Its models map the two association tables and
# deleting a user cascades through them, but no code of that revision inserts
# into them, so Stage 12A may give them a new required column.
STAGE_12A_PREVIOUS_USAGE = PreviousRevisionUsage(
    read_only_tables=frozenset(
        {"user_simulation_associations", "user_report_associations"}
    ),
    nullable_columns_required_by_checks=frozenset({("simulations", "household_id")}),
)
# The revision before the simulation-table removal. It writes every table it
# still maps. Its checks require a standard user's country and one reference
# of each association.
SIMULATION_TABLE_REMOVAL_PREVIOUS_USAGE = PreviousRevisionUsage(
    read_only_tables=frozenset(),
    nullable_columns_required_by_checks=frozenset(
        {
            ("users", "primary_country"),
            ("user_policies", "legacy_policy_id"),
            ("user_household_associations", "legacy_household_id"),
            ("user_simulation_associations", "legacy_simulation_id"),
            ("user_report_associations", "legacy_report_id"),
        }
    ),
)
USER_ASSOCIATION_TABLES = (
    "user_policies",
    "user_household_associations",
    "user_simulation_associations",
    "user_report_associations",
)
COUNTRY_COLUMN_NAMES = frozenset({"country", "country_id", "primary_country"})
# Required values that a parent-revision check constraint restricts.
CHECKED_VALUES = {("datasets", "year"): 2026}


def _is_required_without_default(column: sa.Column) -> bool:
    return not column.nullable and column.server_default is None


def _new_required_columns(parent_table: sa.Table, head_table: sa.Table) -> set[str]:
    return {
        column.name
        for column in head_table.columns
        if column.name not in parent_table.columns
        and _is_required_without_default(column)
    }


def _string_test_value(column_type: sa.String, sequence: Iterator[int]) -> str:
    length = column_type.length or 255
    if length == 64:
        return uuid4().hex + uuid4().hex
    return f"value-{next(sequence)}"[:length]


# Checked in order: a column takes the value of the first type it is an
# instance of, so Enum, a String subclass, comes before String.
TYPED_TEST_VALUES = (
    (sa.Enum, lambda column_type, _sequence: column_type.enums[0]),
    (sa.Uuid, lambda _column_type, _sequence: uuid4()),
    (sa.Boolean, lambda _column_type, _sequence: False),
    (sa.Integer, lambda _column_type, _sequence: 1),
    (sa.Float, lambda _column_type, _sequence: 0.0),
    # Later than every server-default created_at, as retention checks need.
    (
        sa.DateTime,
        lambda _column_type, _sequence: datetime.now(UTC) + timedelta(days=1),
    ),
    (sa.JSON, lambda _column_type, _sequence: {}),
    (sa.String, _string_test_value),
)


def _test_value(table: sa.Table, column: sa.Column, sequence: Iterator[int]):
    if (table.name, column.name) in CHECKED_VALUES:
        return CHECKED_VALUES[(table.name, column.name)]
    if column.name in COUNTRY_COLUMN_NAMES:
        return "us"
    for column_type, test_value in TYPED_TEST_VALUES:
        if isinstance(column.type, column_type):
            return test_value(column.type, sequence)
    msg = f"no test value for {table.name}.{column.name}"
    raise AssertionError(msg)


def _row_values(
    table: sa.Table,
    stored_rows: dict[str, dict],
    sequence: Iterator[int],
    usage: PreviousRevisionUsage,
    *,
    head_table: sa.Table | None = None,
) -> dict:
    """Supply only what the parent revision requires, plus check-bound values.

    ``head_table`` adds the columns head newly requires; only rows of the
    parent's read-only tables, which new code writes, may need them.
    """
    values = {
        column.name: _test_value(table, column, sequence)
        for column in table.columns
        if _is_required_without_default(column)
        or (table.name, column.name) in usage.nullable_columns_required_by_checks
    }
    if head_table is not None:
        for column_name in _new_required_columns(table, head_table):
            values[column_name] = _test_value(
                head_table, head_table.columns[column_name], sequence
            )
    for foreign_key in table.foreign_key_constraints:
        if not any(element.parent.name in values for element in foreign_key.elements):
            continue
        referenced_row = stored_rows[foreign_key.referred_table.name]
        for element in foreign_key.elements:
            values[element.parent.name] = referenced_row[element.column.name]
    return values


def _primary_key_clause(table: sa.Table, row: dict):
    return sa.and_(
        *(column == row[column.name] for column in table.primary_key.columns)
    )


def _insert_and_read_back(
    connection,
    table: sa.Table,
    values: dict,
    *,
    insert_table: sa.Table | None = None,
) -> dict:
    """Insert a row, then read it back through the parent's reflected table.

    Rows of the parent's read-only tables are inserted through head's table,
    as only new code writes them.
    """
    target = insert_table if insert_table is not None else table
    connection.execute(target.insert().values(values))
    # Selecting the reflected table reads every column the parent maps.
    return dict(
        connection.execute(sa.select(table).where(_primary_key_clause(table, values)))
        .mappings()
        .one()
    )


def _rewrite_mapped_columns(connection, table: sa.Table, row: dict) -> None:
    """Update every non-key column the parent maps, as an ORM flush can."""
    key_columns = {column.name for column in table.primary_key.columns} | {
        element.parent.name
        for foreign_key in table.foreign_key_constraints
        for element in foreign_key.elements
    }
    result = connection.execute(
        table.update()
        .where(_primary_key_clause(table, row))
        .values(
            {
                # sa.null() keeps SQL NULL; a bare None becomes JSON null.
                name: sa.null() if value is None else value
                for name, value in row.items()
                if name not in key_columns
            }
        )
    )
    assert result.rowcount == 1, table.name


@dataclass(frozen=True)
class SchemaComparison:
    """A previous revision's reflected tables, a newer schema, and their usage."""

    parent: sa.MetaData
    head: sa.MetaData
    usage: PreviousRevisionUsage


def _assert_user_deletion_cascades(
    connection,
    schemas: SchemaComparison,
    stored_rows: dict[str, dict],
    sequence: Iterator[int],
) -> None:
    """Delete, through the parent's users table, a user who owns Stage 12A rows."""
    parent, head, usage = schemas.parent, schemas.head, schemas.usage
    users = parent.tables["users"]
    owner = _insert_and_read_back(
        connection, users, _row_values(users, stored_rows, sequence, usage)
    )
    owner_rows = {**stored_rows, "users": owner}
    for table_name in USER_ASSOCIATION_TABLES:
        table = parent.tables[table_name]
        head_table = (
            head.tables[table_name] if table_name in usage.read_only_tables else None
        )
        _insert_and_read_back(
            connection,
            table,
            _row_values(table, owner_rows, sequence, usage, head_table=head_table),
            insert_table=head_table,
        )
    identities = head.tables["user_identities"]
    connection.execute(
        identities.insert().values(
            id=uuid4(),
            user_id=owner["id"],
            issuer="https://auth.example.test/",
            subject="google-oauth2|previous-revision",
        )
    )

    result = connection.execute(users.delete().where(users.c.id == owner["id"]))

    assert result.rowcount == 1
    for table_name in (*USER_ASSOCIATION_TABLES, "user_identities"):
        table = head.tables[table_name]
        remaining = connection.execute(
            sa.select(sa.func.count())
            .select_from(table)
            .where(table.c.user_id == owner["id"])
        ).scalar_one()
        assert remaining == 0, table_name


def _assert_newer_schema_serves_previous_usage(
    engine: Engine,
    parent: sa.MetaData,
    head: sa.MetaData,
    usage: PreviousRevisionUsage,
) -> None:
    """Run a previous revision's use of every table it maps against a newer schema.

    Each table of ``parent`` gets a row inserted (supplying only what the
    previous revision requires), read back with every mapped column,
    rewritten and deleted, and a user who owns association rows is deleted so
    the cascades run. The newer schema may not drop a column ``parent`` maps,
    or give a table the previous revision writes a new required column
    without a server default. Every change is rolled back.
    """
    parent_tables = [
        table for table in parent.sorted_tables if table.name != "alembic_version"
    ]
    dropped_columns = sorted(
        f"{table.name}.{column.name}"
        for table in parent_tables
        for column in table.columns
        if table.name not in head.tables
        or column.name not in head.tables[table.name].columns
    )
    assert dropped_columns == []
    tables_with_new_required_columns = {
        table.name: sorted(_new_required_columns(table, head.tables[table.name]))
        for table in parent_tables
        if _new_required_columns(table, head.tables[table.name])
    }
    assert set(tables_with_new_required_columns) <= usage.read_only_tables, (
        tables_with_new_required_columns
    )

    sequence = itertools.count()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            stored_rows: dict[str, dict] = {}
            for table in parent_tables:
                head_table = (
                    head.tables[table.name]
                    if table.name in usage.read_only_tables
                    else None
                )
                stored_rows[table.name] = _insert_and_read_back(
                    connection,
                    table,
                    _row_values(
                        table, stored_rows, sequence, usage, head_table=head_table
                    ),
                    insert_table=head_table,
                )
                _rewrite_mapped_columns(connection, table, stored_rows[table.name])

            _assert_user_deletion_cascades(
                connection, SchemaComparison(parent, head, usage), stored_rows, sequence
            )

            for table in reversed(parent_tables):
                result = connection.execute(
                    table.delete().where(
                        _primary_key_clause(table, stored_rows[table.name])
                    )
                )
                assert result.rowcount == 1, table.name
        finally:
            transaction.rollback()


def test_stage_12a_schema_serves_the_previous_revision() -> None:
    """Run the pre-Stage 12A revision's table usage against the Stage 12A schema.

    A rollback to a pre-Stage 12A release after the simulation-table removal
    first downgrades the schema to the Stage 12A revision, so that schema must
    still serve the pre-Stage 12A release.
    """
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)
    stage_12a_revision = _simulation_table_removal_parent()

    try:
        command.downgrade(config, STAGE_12A_PREVIOUS_REVISION)
        parent = sa.MetaData()
        parent.reflect(engine)
        command.upgrade(config, stage_12a_revision)
        stage_12a = sa.MetaData()
        stage_12a.reflect(engine)

        _assert_newer_schema_serves_previous_usage(
            engine, parent, stage_12a, STAGE_12A_PREVIOUS_USAGE
        )
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def _reflect_previous_revision_usage(engine) -> sa.MetaData:
    """Reflect the tables and columns the previous application revision maps.

    It maps neither the simulation-domain tables nor the retired association
    columns, so the removal revision may drop them while it serves traffic.
    """
    parent = sa.MetaData()
    for table_name, retired_columns in RETIRED_ASSOCIATION_COLUMNS.items():
        sa.Table(
            table_name,
            parent,
            autoload_with=engine,
            include_columns=[
                name
                for name in _columns(engine, table_name)
                if name not in retired_columns
            ],
        )
    parent.reflect(
        engine,
        only=lambda table_name, _metadata: table_name not in SIMULATION_SERVICE_TABLES,
    )
    return parent


def test_simulation_table_removal_serves_the_previous_revision() -> None:
    """Run the previous Public API revision's table usage against head.

    The removal revision drops exactly the simulation-domain tables and the
    retired association columns, which the previous application revision no
    longer maps. The rest of the parent schema is reflected and then used,
    after upgrading, to insert a row into every table it maps (supplying only
    what it requires), read the row back with every mapped column, rewrite
    those columns, delete it, and delete a user who owns association rows so
    the cascades run. Head may not give any table the parent revision writes
    a new required column without a server default.
    """
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, _simulation_table_removal_parent())
        full_parent = sa.MetaData()
        full_parent.reflect(engine)
        parent = _reflect_previous_revision_usage(engine)
        command.upgrade(config, "head")
        head = sa.MetaData()
        head.reflect(engine)

        assert set(full_parent.tables) - set(head.tables) == SIMULATION_SERVICE_TABLES
        assert sorted(
            f"{table.name}.{column.name}"
            for table in full_parent.tables.values()
            if table.name in head.tables
            for column in table.columns
            if column.name not in head.tables[table.name].columns
        ) == sorted(
            f"{table_name}.{column_name}"
            for table_name, retired_columns in RETIRED_ASSOCIATION_COLUMNS.items()
            for column_name in retired_columns
        )

        _assert_newer_schema_serves_previous_usage(
            engine, parent, head, SIMULATION_TABLE_REMOVAL_PREVIOUS_USAGE
        )
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def _schema_snapshot(engine: Engine, table_names: Iterable[str]) -> dict:
    """Describe tables as PostgreSQL reports them, ignoring column order."""
    inspector = inspect(engine)
    snapshot: dict[str, dict] = {}
    for table_name in sorted(table_names):
        snapshot[table_name] = {
            "columns": {
                column["name"]: (
                    repr(column["type"]),
                    column["nullable"],
                    column.get("default"),
                )
                for column in inspector.get_columns(table_name)
            },
            "primary_key": inspector.get_pk_constraint(table_name),
            "foreign_keys": sorted(
                (
                    foreign_key["name"],
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                    tuple(foreign_key["referred_columns"]),
                    foreign_key["options"].get("ondelete"),
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            ),
            "unique_constraints": sorted(
                (constraint["name"], tuple(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(table_name)
            ),
            "check_constraints": sorted(
                (constraint["name"], constraint["sqltext"])
                for constraint in inspector.get_check_constraints(table_name)
            ),
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]), index["unique"])
                for index in inspector.get_indexes(table_name)
            ),
        }
    with engine.connect() as connection:
        snapshot["enum_types"] = {
            type_name: list(
                connection.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum JOIN pg_type "
                        "ON pg_enum.enumtypid = pg_type.oid "
                        "WHERE typname = :type_name ORDER BY enumsortorder"
                    ),
                    {"type_name": type_name},
                ).scalars()
            )
            for type_name in sorted(SIMULATION_DOMAIN_ENUM_TYPES)
        }
    return snapshot


def test_simulation_table_removal_downgrade_restores_the_previous_schema() -> None:
    """The downgrade recreates exactly what the earlier revisions created."""
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)
    compared_tables = SIMULATION_SERVICE_TABLES | RETIRED_ASSOCIATION_COLUMNS.keys()

    try:
        command.downgrade(config, "base")
        command.upgrade(config, _simulation_table_removal_parent())
        created_by_earlier_revisions = _schema_snapshot(engine, compared_tables)
        command.upgrade(config, "head")
        command.downgrade(config, _simulation_table_removal_parent())
        recreated_by_downgrade = _schema_snapshot(engine, compared_tables)

        assert all(created_by_earlier_revisions["enum_types"].values())
        assert recreated_by_downgrade == created_by_earlier_revisions
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def test_upgrade_to_head_validates_the_resulting_schema_against_metadata() -> None:
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, "base")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE unreviewed_runtime_table (id INT)"))

        with pytest.raises(
            V2MigrationTargetError,
            match=r"v2 head schema.*unreviewed_runtime_table",
        ):
            command.upgrade(config, "head")

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() is None
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS unreviewed_runtime_table"))
        command.upgrade(config, "head")
        engine.dispose()


def test_baseline_uses_native_uuid_report_run_idempotency() -> None:
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)

    def idempotency_column_type():
        return next(
            column["type"]
            for column in inspect(engine).get_columns("report_runs")
            if column["name"] == "idempotency_key"
        )

    def report_run_checks() -> set[str]:
        return {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints("report_runs")
        }

    try:
        # The removal revision drops report_runs, so build the schema from
        # empty up to the revision before it: report_runs is the baseline's.
        command.downgrade(config, "base")
        command.upgrade(config, _simulation_table_removal_parent())
        assert isinstance(idempotency_column_type(), postgresql.UUID)
        assert "ck_report_runs_idempotency_key_nonblank" not in report_run_checks()

        model_id = uuid4()
        report_id = uuid4()
        report_run_id = uuid4()
        request_key = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO tax_benefit_models (id, name) VALUES (:id, :name)"),
                {"id": model_id, "name": f"uuid-cast-{model_id.hex[:8]}"},
            )
            connection.execute(
                text(
                    "INSERT INTO reports "
                    "(id, label, country, tax_benefit_model_id, inputs) "
                    "VALUES (:id, 'UUID cast report', 'us', :model_id, '{}')"
                ),
                {"id": report_id, "model_id": model_id},
            )
            connection.execute(
                text(
                    "INSERT INTO report_runs "
                    "(id, report_id, country_package_version, "
                    "policyengine_version, status, trigger, idempotency_key) "
                    "VALUES (:id, :report_id, '1.0', '1.0', 'pending', "
                    "'manual', :request_key)"
                ),
                {
                    "id": report_run_id,
                    "report_id": report_id,
                    "request_key": str(request_key),
                },
            )

        with engine.connect() as connection:
            stored_key = connection.execute(
                text("SELECT idempotency_key FROM report_runs WHERE id = :run_id"),
                {"run_id": report_run_id},
            ).scalar_one()
        assert stored_key == request_key
        assert isinstance(stored_key, UUID)
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM report_runs WHERE id = :run_id"),
                {"run_id": report_run_id},
            )
            connection.execute(
                text("DELETE FROM reports WHERE id = :report_id"),
                {"report_id": report_id},
            )
            connection.execute(
                text("DELETE FROM tax_benefit_models WHERE id = :model_id"),
                {"model_id": model_id},
            )
        command.upgrade(config, "head")
        engine.dispose()


def test_baseline_region_default_enforces_same_model_dataset() -> None:
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)
    first_model_id = uuid4()
    second_model_id = uuid4()
    first_dataset_id = uuid4()
    second_dataset_id = uuid4()

    try:
        command.downgrade(config, BASELINE_REVISION)
        assert "region_datasets" not in inspect(engine).get_table_names(schema="public")
        default_column = next(
            column
            for column in inspect(engine).get_columns("regions")
            if column["name"] == "default_dataset_id"
        )
        assert not default_column["nullable"]
        default_constraint = next(
            constraint
            for constraint in inspect(engine).get_foreign_keys("regions")
            if constraint["name"] == "fk_regions_default_dataset_model_datasets"
        )
        assert default_constraint["constrained_columns"] == [
            "default_dataset_id",
            "tax_benefit_model_id",
        ]
        assert default_constraint["referred_columns"] == [
            "id",
            "tax_benefit_model_id",
        ]

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tax_benefit_models (id, name) "
                    "VALUES (:first_id, :first_name), (:second_id, :second_name)"
                ),
                {
                    "first_id": first_model_id,
                    "first_name": f"region-default-{first_model_id.hex[:8]}",
                    "second_id": second_model_id,
                    "second_name": f"region-default-{second_model_id.hex[:8]}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO datasets "
                    "(id, name, year, is_output_dataset, tax_benefit_model_id) "
                    "VALUES (:first_id, 'logical-input', 2024, false, :first_model), "
                    "(:second_id, 'logical-input', 2024, false, :second_model)"
                ),
                {
                    "first_id": first_dataset_id,
                    "first_model": first_model_id,
                    "second_id": second_dataset_id,
                    "second_model": second_model_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO regions "
                    "(id, code, label, region_type, requires_filter, "
                    "tax_benefit_model_id, default_dataset_id) "
                    "VALUES (:id, 'us', 'United States', 'national', false, "
                    ":model_id, :dataset_id)"
                ),
                {
                    "id": uuid4(),
                    "model_id": first_model_id,
                    "dataset_id": first_dataset_id,
                },
            )

        with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO regions "
                    "(id, code, label, region_type, requires_filter, "
                    "tax_benefit_model_id, default_dataset_id) "
                    "VALUES (:id, 'state/ca', 'California', 'state', false, "
                    ":model_id, :dataset_id)"
                ),
                {
                    "id": uuid4(),
                    "model_id": first_model_id,
                    "dataset_id": second_dataset_id,
                },
            )

        with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO datasets "
                    "(id, name, year, is_output_dataset, "
                    "tax_benefit_model_id) "
                    "VALUES (:id, 'missing-output-path', 2024, true, :model_id)"
                ),
                {"id": uuid4(), "model_id": first_model_id},
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM regions WHERE tax_benefit_model_id IN (:a, :b)"),
                {"a": first_model_id, "b": second_model_id},
            )
            connection.execute(
                text("DELETE FROM datasets WHERE tax_benefit_model_id IN (:a, :b)"),
                {"a": first_model_id, "b": second_model_id},
            )
            connection.execute(
                text("DELETE FROM tax_benefit_models WHERE id IN (:a, :b)"),
                {"a": first_model_id, "b": second_model_id},
            )
        command.upgrade(config, "head")
        engine.dispose()


def test_stage_12a_reshape_refuses_retained_dormant_association_rows() -> None:
    """A retained pre-12A report association stops the reshape unchanged."""
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)
    user_id = uuid4()
    model_id = uuid4()
    report_id = uuid4()

    def reflected(name: str) -> sa.Table:
        return sa.Table(name, sa.MetaData(), autoload_with=engine)

    try:
        command.downgrade(config, STAGE_12A_PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                sa.insert(reflected("users")).values(id=user_id, primary_country="us")
            )
            connection.execute(
                sa.insert(reflected("tax_benefit_models")).values(
                    id=model_id, name=f"stage12a-{model_id.hex[:8]}"
                )
            )
            connection.execute(
                sa.insert(reflected("reports")).values(
                    id=report_id,
                    label="Stage 12A retained report",
                    country="us",
                    tax_benefit_model_id=model_id,
                    inputs={},
                )
            )
            connection.execute(
                sa.insert(reflected("user_report_associations")).values(
                    id=uuid4(), user_id=user_id, report_id=report_id, country="us"
                )
            )

        with pytest.raises(sa.exc.IntegrityError):
            command.upgrade(config, "head")

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() == STAGE_12A_PREVIOUS_REVISION
        _assert_pre_stage_12a_association_shape(engine)
    finally:
        with engine.begin() as connection:
            for table_name, row_id in (
                ("users", user_id),
                ("reports", report_id),
                ("tax_benefit_models", model_id),
            ):
                table = reflected(table_name)
                connection.execute(sa.delete(table).where(table.c.id == row_id))
        command.upgrade(config, "head")
        engine.dispose()
