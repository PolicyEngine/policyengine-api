"""Command-boundary tests for explicit Stage 9 initialization."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from policyengine_api.data.v2.catalog import initialization
from policyengine_api.data.v2.catalog.publication import PublicationEvidence
from policyengine_api.data.v2.settings import (
    V2_DATA_WRITE_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
)
from tests.fixtures.v2_catalog import (
    DEPENDENCY_VERSIONS,
    POLICYENGINE_VERSION,
    normalized_catalog,
)


ENVIRONMENT = {
    V2_DATA_WRITE_DATABASE_URL: (
        "postgresql+psycopg://data-writer:test-password@db."
        "abcdefghijklmnopqrst.supabase.co/postgres?sslmode=require"
    ),
    V2_SUPABASE_PROJECT_REF: "abcdefghijklmnopqrst",
    V2_SUPABASE_ENVIRONMENT: "test-foundation",
    "V2_RUNTIME_DATABASE_URL": "invalid-runtime-value",
    "V2_MIGRATION_DATABASE_URL": "invalid-migration-value",
}


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _evidence() -> PublicationEvidence:
    return PublicationEvidence(
        policyengine_version=POLICYENGINE_VERSION,
        dependency_versions=(
            ("policyengine-core", DEPENDENCY_VERSIONS["policyengine-core"]),
        ),
        entity_counts={"models": 2},
        fallback_summaries=(("us", "state", 1),),
        elapsed_seconds=1.25,
    )


def test_initialization_uses_only_data_write_settings_and_disposes_engine() -> None:
    engine = FakeEngine()
    observed = {}

    def build(settings):
        observed["username"] = settings.connection.url.username
        return engine

    def publish(selected_engine, catalog):
        observed["engine"] = selected_engine
        observed["version"] = catalog.policyengine_version
        return _evidence()

    result = initialization.initialize_catalog(
        ENVIRONMENT,
        extractor=normalized_catalog,
        engine_builder=build,
        publisher=publish,
    )

    assert result == _evidence()
    assert observed == {
        "username": "data-writer",
        "engine": engine,
        "version": POLICYENGINE_VERSION,
    }
    assert engine.disposed


def test_extraction_failure_opens_no_engine() -> None:
    def fail_extraction():
        raise RuntimeError("extraction failed")

    def reject_engine(_settings):
        raise AssertionError("engine must not be built")

    with pytest.raises(RuntimeError, match="extraction failed"):
        initialization.initialize_catalog(
            ENVIRONMENT,
            extractor=fail_extraction,
            engine_builder=reject_engine,
        )


def test_main_emits_typed_success_and_redacted_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(initialization, "initialize_catalog", _evidence)
    assert initialization.main() == 0
    success = capsys.readouterr()
    assert '"outcome": "ok"' in success.out
    assert success.err == ""

    def fail():
        raise RuntimeError("postgresql://user:do-not-print@secret-host/database")

    monkeypatch.setattr(initialization, "initialize_catalog", fail)
    assert initialization.main() == 1
    failure = capsys.readouterr()
    assert '"outcome": "error"' in failure.err
    assert "do-not-print" not in failure.err
    assert "secret-host" not in failure.err


def test_initializer_is_not_imported_by_application_startup_modules() -> None:
    repo = Path(__file__).parents[3]
    for relative_path in (
        "policyengine_api/api.py",
        "policyengine_api/asgi.py",
        "policyengine_api/asgi_factory.py",
    ):
        tree = ast.parse((repo / relative_path).read_text(encoding="utf-8"))
        imported = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(
            module.startswith("policyengine_api.data.v2.catalog.initialization")
            for module in imported
        )
