"""Tests for explicit and secret-safe v2 persistence configuration."""

import pytest

from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_RUNTIME_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
    V2ConfigurationError,
    load_v2_migration_database_settings,
    load_v2_runtime_database_settings,
)


PROJECT_REF = "abcdefghijklmnopqrst"
TARGET_ENVIRONMENT = {
    V2_SUPABASE_PROJECT_REF: PROJECT_REF,
    V2_SUPABASE_ENVIRONMENT: "test-foundation",
}
RUNTIME_URL = (
    "postgresql+psycopg://runtime:test-runtime-password@db.example.com:5432/"
    "postgres?sslmode=require"
)
MIGRATION_URL = (
    "postgresql+psycopg://migrator:test-migration-password@db.example.com:5432/"
    "postgres?sslmode=verify-full"
)


def test_runtime_and_migration_urls_are_explicit_and_separate() -> None:
    environment = {
        **TARGET_ENVIRONMENT,
        V2_RUNTIME_DATABASE_URL: RUNTIME_URL,
        V2_MIGRATION_DATABASE_URL: MIGRATION_URL,
    }

    runtime = load_v2_runtime_database_settings(environment)
    migration = load_v2_migration_database_settings(environment)

    assert runtime.connection.url.username == "runtime"
    assert migration.connection.url.username == "migrator"
    assert runtime.target == migration.target


def test_postgres_password_is_hidden_from_string_and_repr() -> None:
    settings = load_v2_runtime_database_settings(
        {**TARGET_ENVIRONMENT, V2_RUNTIME_DATABASE_URL: RUNTIME_URL}
    )

    rendered = f"{settings!r} {settings.connection}"

    assert "test-runtime-password" not in rendered
    assert "***" in rendered


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+pysqlite:///policyengine.db",
        "mysql+pymysql://user:password@db.example.com/policyengine",
        "postgresql+psycopg://user:password@localhost/postgres?sslmode=require",
        "postgresql+psycopg://user:password@127.0.0.1/postgres?sslmode=require",
        "postgresql+psycopg://user:password@db.example.com/postgres",
    ],
)
def test_runtime_rejects_non_persistent_postgres_targets(url: str) -> None:
    with pytest.raises(V2ConfigurationError):
        load_v2_runtime_database_settings(
            {**TARGET_ENVIRONMENT, V2_RUNTIME_DATABASE_URL: url}
        )


def test_v1_and_debug_settings_never_supply_missing_v2_configuration() -> None:
    environment = {
        **TARGET_ENVIRONMENT,
        "ALEMBIC_DATABASE_URL": "mysql+pymysql://v1:secret@db/v1",
        "POLICYENGINE_DB_PASSWORD": "v1-password",
        "FLASK_DEBUG": "1",
    }

    with pytest.raises(V2ConfigurationError, match=V2_RUNTIME_DATABASE_URL):
        load_v2_runtime_database_settings(environment)
    with pytest.raises(V2ConfigurationError, match=V2_MIGRATION_DATABASE_URL):
        load_v2_migration_database_settings(environment)


def test_configuration_errors_do_not_echo_secret_values() -> None:
    secret_url = "postgresql+psycopg://user:do-not-echo@localhost/postgres"

    with pytest.raises(V2ConfigurationError) as raised:
        load_v2_runtime_database_settings(
            {**TARGET_ENVIRONMENT, V2_RUNTIME_DATABASE_URL: secret_url}
        )

    assert "do-not-echo" not in str(raised.value)
