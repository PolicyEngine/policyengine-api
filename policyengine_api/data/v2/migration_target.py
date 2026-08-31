"""Fail-closed target selection and qualification for v2 Alembic."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import os

from sqlalchemy import Connection, MetaData, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from policyengine_api.data.v2.settings import (
    POSTGRES_DRIVER,
    V2_MIGRATION_DATABASE_URL,
    V2ConfigurationError,
    load_supabase_target_settings,
    parse_persistent_postgres_url,
    validate_supabase_database_identity,
)

V2_ALEMBIC_DISPOSABLE_TEST = "V2_ALEMBIC_DISPOSABLE_TEST"
DISPOSABLE_DATABASE_NAME = "policyengine_v2_alembic_test"
DISPOSABLE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})
MIGRATION_ROLE = "policyengine_v2_migrator"


class V2MigrationTargetError(V2ConfigurationError):
    """Raised before Alembic can modify an unqualified v2 target."""


@dataclass(frozen=True)
class ConfiguredSupabaseTarget:
    environment: str
    project_ref: str
    database_name: str
    migration_role: str
    freshness_audited_on: date
    freshness_audit_passed: bool


@dataclass(frozen=True)
class V2AlembicSettings:
    url: URL
    disposable_test: bool
    target: ConfiguredSupabaseTarget | None


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None or not value.strip():
        raise V2MigrationTargetError(f"{name} is required")
    return value.strip()


def _parse_url(raw_url: str) -> URL:
    try:
        url = make_url(raw_url)
    except ArgumentError as error:
        raise V2MigrationTargetError(
            f"{V2_MIGRATION_DATABASE_URL} is not a valid URL"
        ) from error
    if url.drivername != POSTGRES_DRIVER:
        raise V2MigrationTargetError(
            f"{V2_MIGRATION_DATABASE_URL} must use the {POSTGRES_DRIVER} driver"
        )
    return url


def _validate_disposable_url(url: URL) -> None:
    if url.host not in DISPOSABLE_HOSTS or url.database != DISPOSABLE_DATABASE_NAME:
        raise V2MigrationTargetError(
            "disposable v2 Alembic mode requires the isolated local "
            f"{DISPOSABLE_DATABASE_NAME} database"
        )
    if not url.username or url.password is None:
        raise V2MigrationTargetError(
            "disposable v2 Alembic mode requires explicit test credentials"
        )


def load_v2_alembic_settings(
    environ: Mapping[str, str] | None = None,
) -> V2AlembicSettings:
    """Select either the configured persistent target or isolated test Postgres."""

    values = os.environ if environ is None else environ
    raw_url = _required(values, V2_MIGRATION_DATABASE_URL)
    url = _parse_url(raw_url)
    disposable_value = values.get(V2_ALEMBIC_DISPOSABLE_TEST)
    if disposable_value not in {None, "", "0", "1"}:
        raise V2MigrationTargetError(
            f"{V2_ALEMBIC_DISPOSABLE_TEST} must be 1 when explicitly enabled"
        )
    if disposable_value == "1":
        _validate_disposable_url(url)
        return V2AlembicSettings(url=url, disposable_test=True, target=None)

    persistent = parse_persistent_postgres_url(
        raw_url,
        setting_name=V2_MIGRATION_DATABASE_URL,
    )
    try:
        configured_identity = load_supabase_target_settings(values)
        validate_supabase_database_identity(
            persistent,
            configured_identity,
            setting_name=V2_MIGRATION_DATABASE_URL,
        )
    except V2ConfigurationError as error:
        raise V2MigrationTargetError(str(error)) from error
    target = ConfiguredSupabaseTarget(
        environment=configured_identity.environment,
        project_ref=configured_identity.project_ref,
        database_name="postgres",
        migration_role=MIGRATION_ROLE,
        freshness_audited_on=date(2026, 8, 13),
        freshness_audit_passed=True,
    )
    return V2AlembicSettings(
        url=persistent.url,
        disposable_test=False,
        target=target,
    )


def qualify_v2_connection(
    connection: Connection,
    settings: V2AlembicSettings,
) -> None:
    """Verify live target identity and first-use state before Alembic runs."""

    if connection.dialect.name != "postgresql":
        raise V2MigrationTargetError("v2 Alembic requires a Postgres connection")
    if settings.disposable_test:
        return

    target = settings.target
    if target is None:
        raise V2MigrationTargetError("persistent v2 Alembic target is missing")
    identity = connection.execute(text("SELECT current_database(), current_user")).one()
    if identity[0] != target.database_name or identity[1] != target.migration_role:
        raise V2MigrationTargetError(
            "the live database or migration identity does not match the configured "
            "v2 target"
        )
    can_create = connection.execute(
        text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
    ).scalar_one()
    if can_create is not True:
        raise V2MigrationTargetError(
            "the configured v2 migration identity lacks public schema CREATE"
        )

    public_tables = set(inspect(connection).get_table_names(schema="public"))
    if "alembic_version" not in public_tables:
        if not target.freshness_audit_passed:
            raise V2MigrationTargetError(
                "the configured first-use freshness audit has not passed"
            )
        if public_tables:
            raise V2MigrationTargetError(
                "the unstamped v2 target is not fresh; reset and adoption are "
                "prohibited"
            )


def validate_v2_head_schema(connection: Connection, metadata: MetaData) -> None:
    """Require live application tables to match authoritative ORM metadata."""

    public_tables = set(inspect(connection).get_table_names(schema="public"))
    application_tables = public_tables - {"alembic_version"}
    metadata_tables = {table.name for table in metadata.tables.values()}
    unexpected = application_tables - metadata_tables
    missing = metadata_tables - application_tables
    if unexpected or missing:
        raise V2MigrationTargetError(
            "the v2 head schema differs from SQLModel metadata: "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
