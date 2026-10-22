"""Exercise the isolated v2 Alembic lifecycle against disposable Postgres."""

import itertools
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.dialects import postgresql

from policyengine_api.constants import REPO
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
SAVED_POLICY_RENAME_PARENT_REVISION = "fbb7488ebe8a"
V2_TABLE_NAMES = frozenset(table.name for table in V2_METADATA.tables.values())


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
        ("user_policy_associations", "policy"),
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
        if foreign_key["referred_table"] == "user_policy_associations"
    )
    assert report_policy_key["options"]["ondelete"] == "SET NULL"
    for table_name in ("user_simulation_associations", "user_report_associations"):
        columns = _columns(engine, table_name)
        assert columns["country"]["nullable"]
        assert columns["label"]["nullable"]
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


# Dormant at the parent revision: its models map these tables, and deleting a
# user cascades through them, but no parent-revision code inserts into them.
# They are the only tables Stage 12A may give a new required column.
PARENT_REVISION_READ_ONLY_TABLES = frozenset(
    {"user_simulation_associations", "user_report_associations"}
)
USER_ASSOCIATION_TABLES = (
    "user_policies",
    "user_household_associations",
    "user_simulation_associations",
    "user_report_associations",
)
# Tables head renamed, keyed by their name at the parent revision. The
# previous release's statements name the old table, which head does not have
# until a view under that name exists (test_previous_release_still_finds_
# user_policies), so its column usage runs against the renamed table here.
RENAMED_AT_HEAD = {"user_policies": "user_policy_associations"}
COUNTRY_COLUMN_NAMES = frozenset({"country", "country_id", "primary_country"})
# Nullable references that a parent-revision check constraint requires.
REFERENCES_REQUIRED_BY_CHECKS = frozenset({("simulations", "household_id")})
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
        or (table.name, column.name) in REFERENCES_REQUIRED_BY_CHECKS
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


def _assert_user_deletion_cascades(
    connection,
    parent: sa.MetaData,
    head: sa.MetaData,
    stored_rows: dict[str, dict],
    sequence: Iterator[int],
) -> None:
    """Delete, through the parent's users table, a user who owns Stage 12A rows."""
    users = parent.tables["users"]
    owner = _insert_and_read_back(
        connection, users, _row_values(users, stored_rows, sequence)
    )
    owner_rows = {**stored_rows, "users": owner}
    for table_name in USER_ASSOCIATION_TABLES:
        table = parent.tables[table_name]
        head_table = (
            head.tables[table_name]
            if table_name in PARENT_REVISION_READ_ONLY_TABLES
            else None
        )
        _insert_and_read_back(
            connection,
            table,
            _row_values(table, owner_rows, sequence, head_table=head_table),
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
        table = head.tables[RENAMED_AT_HEAD.get(table_name, table_name)]
        remaining = connection.execute(
            sa.select(sa.func.count())
            .select_from(table)
            .where(table.c.user_id == owner["id"])
        ).scalar_one()
        assert remaining == 0, table_name


def test_stage_12a_schema_serves_the_previous_revision() -> None:
    """Run the previous Public API revision's table usage against head.

    The parent revision's schema is reflected and then used, after upgrading,
    to insert a row into every table it maps (supplying only what it
    requires), read the row back with every mapped column, rewrite those
    columns, delete it, and delete a user who owns Stage 12A rows so the
    cascades run. Head may not give any table the parent revision writes a
    new required column without a server default. A table head renamed is
    used under its new name (``RENAMED_AT_HEAD``).
    """
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, STAGE_12A_PREVIOUS_REVISION)
        parent = sa.MetaData()
        parent.reflect(engine)
        for parent_name, head_name in RENAMED_AT_HEAD.items():
            parent.tables[parent_name].name = head_name
        command.upgrade(config, "head")
        head = sa.MetaData()
        head.reflect(engine)
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
        assert set(tables_with_new_required_columns) <= (
            PARENT_REVISION_READ_ONLY_TABLES
        ), tables_with_new_required_columns

        sequence = itertools.count()
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                stored_rows: dict[str, dict] = {}
                for table in parent_tables:
                    head_table = (
                        head.tables[table.name]
                        if table.name in PARENT_REVISION_READ_ONLY_TABLES
                        else None
                    )
                    stored_rows[table.name] = _insert_and_read_back(
                        connection,
                        table,
                        _row_values(
                            table, stored_rows, sequence, head_table=head_table
                        ),
                        insert_table=head_table,
                    )
                    _rewrite_mapped_columns(connection, table, stored_rows[table.name])

                _assert_user_deletion_cascades(
                    connection, parent, head, stored_rows, sequence
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
        command.upgrade(config, "head")
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


@pytest.mark.xfail(
    strict=True,
    raises=sa.exc.ProgrammingError,
    reason=(
        "Head has no view named user_policies yet. Autogeneration cannot "
        "create one, and a hand-written view needs a human migration decision "
        "(see the saved-policy table rename in the Alembic migrations skill); "
        "until then the release running during a deploy cannot find the table."
    ),
)
def test_previous_release_still_finds_user_policies() -> None:
    """The release running during the deploy reads saved policies by the old name."""
    engine = create_engine(_disposable_url())
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT count(*) FROM user_policies")).scalar_one()
    finally:
        engine.dispose()


def _constraint_names(engine, table_name: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = to_regclass(:table_name)"
                ),
                {"table_name": f"public.{table_name}"},
            ).scalars()
        )


def _index_names(engine, table_name: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = :table_name"
                ),
                {"table_name": table_name},
            ).scalars()
        )


def _referring_foreign_keys(engine, table_name: str) -> set[tuple[str, str]]:
    with engine.connect() as connection:
        return {
            (row.on_table, row.conname)
            for row in connection.execute(
                text(
                    "SELECT conrelid::regclass::text AS on_table, conname "
                    "FROM pg_constraint WHERE contype = 'f' "
                    "AND confrelid = to_regclass(:table_name)"
                ),
                {"table_name": f"public.{table_name}"},
            )
        }


def _closure_of_referred_tables(
    metadata: sa.MetaData, table_names: set[str]
) -> set[str]:
    closure: set[str] = set()
    pending = list(table_names)
    while pending:
        table_name = pending.pop()
        if table_name in closure:
            continue
        closure.add(table_name)
        pending.extend(
            foreign_key.referred_table.name
            for foreign_key in metadata.tables[table_name].foreign_key_constraints
        )
    return closure


def _saved_policy_with_references(connection, parent: sa.MetaData) -> dict:
    """Store a user, a policy, a saved policy, its v1 mapping and a report."""
    sequence = itertools.count()
    stored_rows: dict[str, dict] = {}
    owner_tables = _closure_of_referred_tables(parent, {"users", "policies"})
    for table in parent.sorted_tables:
        if table.name in owner_tables:
            values = _row_values(table, stored_rows, sequence)
            if table.name == "users":
                # A standard user needs a country (ck_users_standard_primary_country).
                values["primary_country"] = "us"
            stored_rows[table.name] = _insert_and_read_back(connection, table, values)
    saved_policy_id = uuid4()
    connection.execute(
        parent.tables["user_policies"]
        .insert()
        .values(
            id=saved_policy_id,
            user_id=stored_rows["users"]["id"],
            policy_id=stored_rows["policies"]["id"],
            country_id=stored_rows["policies"]["country_id"],
            name="Saved reform",
            baseline="current-law",
        )
    )
    connection.execute(
        parent.tables["legacy_user_policy_mappings"]
        .insert()
        .values(
            id=uuid4(),
            country_id=stored_rows["policies"]["country_id"],
            legacy_user_policy_id=41,
            user_policy_id=saved_policy_id,
            fingerprint_version=1,
            fingerprint_sha256="a" * 64,
        )
    )
    report_id = uuid4()
    connection.execute(
        parent.tables["user_report_associations"]
        .insert()
        .values(
            id=report_id,
            user_id=stored_rows["users"]["id"],
            country_id=stored_rows["policies"]["country_id"],
            legacy_report_id=42,
            user_policy_id=saved_policy_id,
            baseline_user_policy_id=saved_policy_id,
        )
    )
    return {
        "stored_rows": stored_rows,
        "saved_policy_id": saved_policy_id,
        "report_id": report_id,
    }


def _saved_policy_row(connection, table_name: str, saved_policy_id: UUID) -> dict:
    return dict(
        connection.execute(
            sa.select(sa.text("*"))
            .select_from(sa.table(table_name))
            .where(sa.column("id") == saved_policy_id)
        )
        .mappings()
        .one()
    )


def _delete_saved_policy_rows(engine, parent: sa.MetaData, saved: dict) -> None:
    """Remove the stored rows at head, children first, so later tests start clean."""
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM user_report_associations WHERE id = :id"),
            {"id": saved["report_id"]},
        )
        # Deleting the saved policy cascades to its v1 mapping.
        connection.execute(
            text("DELETE FROM user_policy_associations WHERE id = :id"),
            {"id": saved["saved_policy_id"]},
        )
        for table in reversed(parent.sorted_tables):
            stored_row = saved["stored_rows"].get(table.name)
            if stored_row is not None:
                connection.execute(
                    table.delete().where(_primary_key_clause(table, stored_row))
                )


# The names head gives the renamed table's constraints, indexes and the
# foreign keys that refer to it. Names longer than PostgreSQL's 63 characters
# end in a hash, as SQLAlchemy shortens the model's convention names.
SAVED_POLICY_SCHEMA_NAMES_AT_HEAD = {
    "constraints": {
        "pk_user_policy_associations",
        "uq_user_policy_associations_id_country",
        "ck_user_policy_associations_country",
        "ck_user_policy_associations_policy_ref",
        "ck_user_policy_associations_baseline",
        "fk_user_policy_associations_policy_country",
        "fk_user_policy_associations_user_id_users",
    },
    "indexes": {
        "pk_user_policy_associations",
        "uq_user_policy_associations_id_country",
        "ix_user_policy_associations_user_id",
        "ix_user_policy_associations_policy_id",
        "ix_user_policies_country_user_created_id",
        "ix_user_policies_country_policy",
        "ix_user_policies_country_legacy_policy",
    },
    "referring_foreign_keys": {
        (
            "legacy_user_policy_mappings",
            "fk_legacy_user_policy_mappings_association_country",
        ),
        (
            "user_report_associations",
            "fk_user_report_associations_user_policy_id_user_policy__0820",
        ),
        (
            "user_report_associations",
            "fk_user_report_associations_baseline_user_policy_id_use_0a3d",
        ),
    },
}
RENAME_PRIVILEGE_PROBE_ROLE = "rename_privilege_probe"


def _schema_names(engine, table_name: str) -> dict[str, set]:
    return {
        "constraints": _constraint_names(engine, table_name),
        "indexes": _index_names(engine, table_name),
        "referring_foreign_keys": _referring_foreign_keys(engine, table_name),
    }


def _saved_policy_references(connection, saved: dict) -> tuple:
    """Return the saved policy a v1 mapping and a report's two keys point at."""
    mapped = connection.execute(
        text(
            "SELECT user_policy_id FROM legacy_user_policy_mappings "
            "WHERE legacy_user_policy_id = 41"
        )
    ).scalar_one_or_none()
    report_references = connection.execute(
        text(
            "SELECT user_policy_id, baseline_user_policy_id "
            "FROM user_report_associations WHERE id = :id"
        ),
        {"id": saved["report_id"]},
    ).one()
    return (mapped, *report_references)


def _references_after_deleting_saved_policy(engine, saved: dict) -> tuple:
    """Delete the saved policy in a rolled-back transaction; return the references.

    The v1 mapping cascades away and the report's keys are set to null.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text("DELETE FROM user_policy_associations WHERE id = :id"),
                {"id": saved["saved_policy_id"]},
            )
            return _saved_policy_references(connection, saved)
        finally:
            transaction.rollback()


def _drop_rename_privilege_probe(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = "
                f"'{RENAME_PRIVILEGE_PROBE_ROLE}') THEN "
                f"DROP OWNED BY {RENAME_PRIVILEGE_PROBE_ROLE}; "
                f"DROP ROLE {RENAME_PRIVILEGE_PROBE_ROLE}; END IF; END $$"
            )
        )


def test_saved_policy_rename_keeps_rows_references_and_privileges() -> None:
    """Upgrading renames the table in place, and downgrading renames it back.

    Saved policies, their v1 mappings and the reports that name them survive
    both directions, the references and a table grant follow the table, and
    the constraints and indexes named after the table take its name. The
    downgrade restores every name the parent revision had.
    """
    config = _config()
    engine = create_engine(_disposable_url())
    parent = sa.MetaData()
    saved = None
    try:
        command.downgrade(config, SAVED_POLICY_RENAME_PARENT_REVISION)
        parent.reflect(engine)
        names_at_parent = _schema_names(engine, "user_policies")
        _drop_rename_privilege_probe(engine)
        with engine.begin() as connection:
            saved = _saved_policy_with_references(connection, parent)
            connection.execute(text(f"CREATE ROLE {RENAME_PRIVILEGE_PROBE_ROLE}"))
            connection.execute(
                text(
                    "GRANT SELECT, UPDATE ON user_policies TO "
                    f"{RENAME_PRIVILEGE_PROBE_ROLE}"
                )
            )
            before = _saved_policy_row(
                connection, "user_policies", saved["saved_policy_id"]
            )
        saved_policy_id = saved["saved_policy_id"]

        command.upgrade(config, "head")

        table_names = set(inspect(engine).get_table_names(schema="public"))
        assert "user_policies" not in table_names
        with engine.connect() as connection:
            after = _saved_policy_row(
                connection, "user_policy_associations", saved_policy_id
            )
            references = _saved_policy_references(connection, saved)
            granted = connection.execute(
                text(
                    f"SELECT has_table_privilege('{RENAME_PRIVILEGE_PROBE_ROLE}', "
                    "'public.user_policy_associations', 'SELECT, UPDATE')"
                )
            ).scalar_one()
        assert after == before
        assert references == (saved_policy_id, saved_policy_id, saved_policy_id)
        assert granted
        assert (
            _schema_names(engine, "user_policy_associations")
            == SAVED_POLICY_SCHEMA_NAMES_AT_HEAD
        )
        assert _references_after_deleting_saved_policy(engine, saved) == (
            None,
            None,
            None,
        )

        command.downgrade(config, SAVED_POLICY_RENAME_PARENT_REVISION)

        table_names = set(inspect(engine).get_table_names(schema="public"))
        assert "user_policy_associations" not in table_names
        with engine.connect() as connection:
            restored = _saved_policy_row(connection, "user_policies", saved_policy_id)
            restored_references = _saved_policy_references(connection, saved)
        assert restored == before
        assert restored_references == references
        assert _schema_names(engine, "user_policies") == names_at_parent
    finally:
        command.upgrade(config, "head")
        if saved is not None:
            _delete_saved_policy_rows(engine, parent, saved)
        _drop_rename_privilege_probe(engine)
        engine.dispose()
