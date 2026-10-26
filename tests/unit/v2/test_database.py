"""Tests for lazy process-owned v2 engine and SQLModel Session factories."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2 import database
from policyengine_api.data.v2.models import V2_METADATA, TaxBenefitModel
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
        V2_SUPABASE_ENVIRONMENT: "test-foundation",
        V2_RUNTIME_DATABASE_URL: (
            f"postgresql+psycopg://{username}:test-password@db."
            "abcdefghijklmnopqrst.supabase.co:5432/postgres?sslmode=require"
        ),
        V2_MIGRATION_DATABASE_URL: (
            "postgresql+psycopg://migrator:test-password@db."
            "abcdefghijklmnopqrst.supabase.co:5432/postgres?sslmode=require"
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


def test_engine_uses_one_timeout_for_pool_connection_and_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_v2_runtime_database_settings(_environment())
    captured: dict[str, object] = {}
    expected_engine = object()

    def capture_create_engine(url: object, **options: object) -> object:
        captured["url"] = url
        captured.update(options)
        return expected_engine

    monkeypatch.setattr(database, "create_engine", capture_create_engine)

    engine = database.build_v2_engine(settings)

    assert engine is expected_engine
    assert captured["url"] is settings.connection.url
    assert database.DATABASE_TIMEOUT_SECONDS == 5
    assert captured["pool_timeout"] == database.DATABASE_TIMEOUT_SECONDS
    assert captured["connect_args"] == {
        "connect_timeout": database.DATABASE_TIMEOUT_SECONDS,
        "options": (
            f"-c statement_timeout={database.DATABASE_TIMEOUT_SECONDS * 1_000}"
        ),
    }


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
    parent_pid = database._engine_state.engine_pid
    assert parent_pid is not None
    monkeypatch.setattr(database.os, "getpid", lambda: parent_pid + 1)

    child_engine = database.get_v2_engine(settings)

    assert child_engine is not parent_engine
    assert database._engine_state.engine_pid == parent_pid + 1


def test_read_sessions_share_the_runtime_pool_without_transactions() -> None:
    settings = load_v2_runtime_database_settings(_environment())

    read_factory = database.get_v2_read_session_factory(settings)
    runtime_engine = database.get_v2_engine(settings)

    with read_factory() as session:
        bind = session.get_bind()
        assert bind.get_execution_options()["isolation_level"] == "AUTOCOMMIT"
        assert bind.pool is runtime_engine.pool
    assert database.get_v2_read_session_factory(settings) is read_factory
    assert runtime_engine.get_execution_options().get("isolation_level") is None


def test_read_session_factory_is_rebuilt_with_the_engine() -> None:
    settings = load_v2_runtime_database_settings(_environment())
    first = database.get_v2_read_session_factory(settings)

    database.close_v2_database()

    assert database.get_v2_read_session_factory(settings) is not first


def test_read_sessions_refuse_to_write_rows() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    V2_METADATA.create_all(engine)
    read_factory = database.build_v2_read_session_factory(engine)

    with read_factory() as session:
        session.add(TaxBenefitModel(name="policyengine-test"))
        with pytest.raises(database.ReadOnlySessionError):
            session.flush()

    with Session(engine) as session:
        assert session.exec(select(TaxBenefitModel)).all() == []
    engine.dispose()


def test_only_the_metadata_reader_opens_read_sessions() -> None:
    package = Path(database.__file__).parents[2]
    users = sorted(
        str(module.relative_to(package))
        for module in package.rglob("*.py")
        if module.name != "database.py"
        and (
            "get_v2_read_session_factory" in module.read_text(encoding="utf-8")
            or "build_v2_read_session_factory" in module.read_text(encoding="utf-8")
        )
    )

    assert users == ["fastapi_routes/dependencies.py"]
    dependencies_source = (package / "fastapi_routes/dependencies.py").read_text(
        encoding="utf-8"
    )
    reader_factory = dependencies_source.split(
        "def _default_v2_metadata_reader_factory"
    )[1].split("\ndef ")[0]
    assert "get_v2_read_session_factory" in reader_factory
    assert dependencies_source.count("get_v2_read_session_factory") == 2
