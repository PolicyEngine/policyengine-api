"""Tests for lazy process-owned v2 engine and SQLModel Session factories."""

from collections.abc import Iterator

import pytest
from sqlmodel import Session

from policyengine_api.data.v2 import database
from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_RUNTIME_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
    V2ConfigurationError,
    load_v2_migration_database_settings,
    load_v2_runtime_database_settings,
)


def _environment(*, username: str = "runtime") -> dict[str, str]:
    return {
        V2_SUPABASE_PROJECT_REF: "abcdefghijklmnopqrst",
        V2_SUPABASE_ENVIRONMENT: "production-foundation",
        V2_RUNTIME_DATABASE_URL: (
            f"postgresql+psycopg://{username}:test-password@db.example.com:5432/"
            "postgres?sslmode=require"
        ),
        V2_MIGRATION_DATABASE_URL: (
            "postgresql+psycopg://migrator:test-password@db.example.com:5432/"
            "postgres?sslmode=require"
        ),
    }


@pytest.fixture(autouse=True)
def _clear_v2_database_state() -> Iterator[None]:
    database.close_v2_database()
    yield
    database.close_v2_database()


def test_engine_construction_is_lazy_and_reused_without_connecting() -> None:
    settings = load_v2_runtime_database_settings(_environment())

    first = database.get_v2_engine(settings)
    second = database.get_v2_engine(settings)

    assert first is second
    assert first.url.drivername == "postgresql+psycopg"
    assert first.pool.checkedout() == 0


def test_session_factory_builds_sqlmodel_sessions() -> None:
    settings = load_v2_runtime_database_settings(_environment())
    factory = database.get_v2_session_factory(settings)

    with factory() as session:
        assert isinstance(session, Session)
        assert session.bind is database.get_v2_engine(settings)


def test_process_engine_cannot_silently_change_target() -> None:
    first = load_v2_runtime_database_settings(_environment(username="runtime"))
    second = load_v2_runtime_database_settings(_environment(username="other-runtime"))
    database.get_v2_engine(first)

    with pytest.raises(V2ConfigurationError, match="different explicit target"):
        database.get_v2_engine(second)


def test_migration_credentials_are_not_selected_as_runtime_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    migration = load_v2_migration_database_settings(environment)
    for key, value in environment.items():
        if key != V2_RUNTIME_DATABASE_URL:
            monkeypatch.setenv(key, value)
    monkeypatch.delenv(V2_RUNTIME_DATABASE_URL, raising=False)

    with pytest.raises(V2ConfigurationError, match=V2_RUNTIME_DATABASE_URL):
        database.get_v2_engine()

    assert migration.connection.url.username == "migrator"


def test_forked_process_state_builds_a_new_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_v2_runtime_database_settings(_environment())
    parent_engine = database.get_v2_engine(settings)
    parent_pid = database._engine_pid
    assert parent_pid is not None
    monkeypatch.setattr(database.os, "getpid", lambda: parent_pid + 1)

    child_engine = database.get_v2_engine(settings)

    assert child_engine is not parent_engine
    assert database._engine_pid == parent_pid + 1
