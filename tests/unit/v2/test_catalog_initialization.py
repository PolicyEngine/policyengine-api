"""Command-boundary tests for explicit Stage 9 initialization."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from policyengine_api.data.v2.catalog import initialization
from policyengine_api.data.v2.catalog.errors import CatalogExtractionError
from policyengine_api.data.v2.catalog.publication import PublicationEvidence
from policyengine_api.data.v2.catalog.region_data_verification import (
    RegionDataVerificationError,
)
from policyengine_api.data.v2.settings import (
    V2_DATA_WRITE_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
    V2ConfigurationError,
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
    "SIMULATION_ENTRYPOINT_URL": "https://simulation.example",
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

    def verify(selected_engine, catalog, environ):
        assert "engine" not in observed
        observed["verified"] = (
            selected_engine,
            catalog.policyengine_version,
            environ,
        )

    def record_spm(selected_engine, catalog, environ):
        assert "engine" in observed
        observed["spm"] = (selected_engine, catalog.policyengine_version, environ)

    result = initialization.initialize_catalog(
        ENVIRONMENT,
        extractor=normalized_catalog,
        engine_builder=build,
        steps=initialization.PublicationSteps(
            verify_region_data=verify,
            publish=publish,
            record_spm_availability=record_spm,
        ),
    )

    assert result == _evidence()
    assert observed == {
        "username": "data-writer",
        "verified": (engine, POLICYENGINE_VERSION, ENVIRONMENT),
        "engine": engine,
        "version": POLICYENGINE_VERSION,
        "spm": (engine, POLICYENGINE_VERSION, ENVIRONMENT),
    }
    assert engine.disposed


def test_region_data_failure_publishes_nothing_and_disposes_engine() -> None:
    engine = FakeEngine()

    def reject(_engine, _catalog, _environ):
        msg = "the certified dataset d has no household column c"
        raise RegionDataVerificationError(msg)

    def refuse_publication(_engine, _catalog):
        msg = "publication must not start"
        raise AssertionError(msg)

    with pytest.raises(RegionDataVerificationError, match="no household column"):
        initialization.initialize_catalog(
            ENVIRONMENT,
            extractor=normalized_catalog,
            engine_builder=lambda _settings: engine,
            steps=initialization.PublicationSteps(
                verify_region_data=reject, publish=refuse_publication
            ),
        )
    assert engine.disposed


def test_installed_verification_reads_artifacts_with_the_hugging_face_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {}

    class RecordingInspector:
        def __init__(self, *, token):
            observed["token"] = token

    def record(catalog, inspector, *, countries):
        observed["call"] = (catalog.policyengine_version, type(inspector), countries)

    monkeypatch.setattr(initialization, "HuggingFaceDataInspector", RecordingInspector)
    monkeypatch.setattr(initialization, "verify_region_data", record)

    initialization.verify_installed_region_data(
        normalized_catalog(), ("uk",), {"HUGGING_FACE_TOKEN": "read-token"}
    )
    assert observed == {
        "token": "read-token",
        "call": (POLICYENGINE_VERSION, RecordingInspector, ("uk",)),
    }

    initialization.verify_installed_region_data(normalized_catalog(), ("us",), {})
    assert observed == {
        "token": None,
        "call": (POLICYENGINE_VERSION, RecordingInspector, ("us",)),
    }


@pytest.mark.parametrize("environ", [{}, {"HUGGING_FACE_TOKEN": ""}])
def test_uk_verification_requires_the_hugging_face_token_before_reading(
    monkeypatch: pytest.MonkeyPatch,
    environ: dict[str, str],
) -> None:
    def refuse(*_args, **_kwargs):
        msg = "no artifact may be read without the token"
        raise AssertionError(msg)

    monkeypatch.setattr(initialization, "HuggingFaceDataInspector", refuse)
    monkeypatch.setattr(initialization, "verify_region_data", refuse)

    with pytest.raises(
        V2ConfigurationError,
        match=r"^HUGGING_FACE_TOKEN must be set to read the certified uk data, "
        r"whose repository is private$",
    ):
        initialization.verify_installed_region_data(
            normalized_catalog(), ("us", "uk"), environ
        )


def test_default_verification_checks_only_countries_not_yet_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    catalog = normalized_catalog()
    observed = {}

    def find_unpublished(selected_engine, selected_catalog):
        observed["found"] = (selected_engine, selected_catalog)
        return ("uk",)

    def verify(selected_catalog, countries, environ):
        observed["verified"] = (selected_catalog, countries, environ)

    monkeypatch.setattr(initialization, "unpublished_countries", find_unpublished)
    monkeypatch.setattr(initialization, "verify_installed_region_data", verify)

    initialization.verify_unpublished_region_data(engine, catalog, ENVIRONMENT)

    assert observed == {
        "found": (engine, catalog),
        "verified": (catalog, ("uk",), ENVIRONMENT),
    }


def test_main_reports_a_region_data_failure_with_its_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail():
        msg = (
            "the certified dataset d has no household column c, which 1 uk region "
            "filters on (constituency/x)"
        )
        raise RegionDataVerificationError(msg)

    monkeypatch.setattr(initialization, "initialize_catalog", fail)

    assert initialization.main() == 1
    failure = capsys.readouterr()
    assert '"type": "RegionDataVerificationError"' in failure.err
    assert "which 1 uk region filters on" in failure.err


def test_extraction_failure_opens_no_engine() -> None:
    def fail_extraction():
        msg = "extraction failed"
        raise RuntimeError(msg)

    def reject_engine(_settings):
        msg = "engine must not be built"
        raise AssertionError(msg)

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
        msg = "postgresql://user:do-not-print@secret-host/database"
        raise RuntimeError(msg)

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


def test_region_data_errors_are_not_reported_as_extraction_errors() -> None:
    # Extraction errors are raised before any database access; verification
    # runs after reading the stored versions and reads certified data over the
    # network.
    assert not issubclass(RegionDataVerificationError, CatalogExtractionError)


def test_main_reports_a_missing_hugging_face_token_with_its_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def verify_without_token():
        initialization.verify_installed_region_data(normalized_catalog(), ("uk",), {})

    monkeypatch.setattr(initialization, "initialize_catalog", verify_without_token)

    assert initialization.main() == 1
    failure = capsys.readouterr()
    assert '"type": "V2ConfigurationError"' in failure.err
    assert "HUGGING_FACE_TOKEN must be set to read the certified uk data" in (
        failure.err
    )


def test_a_missing_simulation_service_url_stops_before_extraction() -> None:
    def refuse_extraction():
        msg = "extraction must not start"
        raise AssertionError(msg)

    environment = {
        name: value
        for name, value in ENVIRONMENT.items()
        if name != "SIMULATION_ENTRYPOINT_URL"
    }

    with pytest.raises(V2ConfigurationError, match="SIMULATION_ENTRYPOINT_URL"):
        initialization.initialize_catalog(environment, extractor=refuse_extraction)
