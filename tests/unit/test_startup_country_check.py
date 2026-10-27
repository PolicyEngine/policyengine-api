"""The startup check that the v2 countries table matches the country list in code."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError

from policyengine_api import startup_country_check
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.services.v2.countries.validators import (
    CountryListMismatchError,
)
from policyengine_api.startup_country_check import check_countries_table_at_startup
from policyengine_api.supported_countries import SUPPORTED_COUNTRY_IDS

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

V2_RUNTIME_SECRET_RESOURCE = "projects/example/secrets/v2-runtime/versions/latest"


@pytest.fixture(autouse=True)
def enabled_startup_check_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-enable the check's logger, which Alembic's logging setup disables.

    Tests that run Alembic commands load its logging configuration, which
    disables every logger that already exists, including this module's.
    """
    monkeypatch.setattr(startup_country_check.logger, "disabled", False)


class FakeCountryListVerifier:
    """Record each verification, then raise ``error`` if one is set."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.verified_country_lists: list[tuple[str, ...]] = []

    def verify_countries_match_code_list(
        self, listed_country_ids: Iterable[str]
    ) -> None:
        self.verified_country_lists.append(tuple(listed_country_ids))
        if self.error is not None:
            raise self.error


class CountingVerifierFactory:
    """Return one verifier and count how often startup asks for it."""

    def __init__(self, verifier: FakeCountryListVerifier) -> None:
        self.verifier = verifier
        self.calls = 0

    def __call__(self) -> FakeCountryListVerifier:
        self.calls += 1
        return self.verifier


def test_startup_without_a_v2_runtime_database_skips_the_check() -> None:
    factory = CountingVerifierFactory(FakeCountryListVerifier())

    check_countries_table_at_startup(
        environ={"FLASK_DEBUG": "1"}, verifier_factory=factory
    )

    assert factory.calls == 0


def test_blank_selection_variables_skip_the_check() -> None:
    factory = CountingVerifierFactory(FakeCountryListVerifier())

    check_countries_table_at_startup(
        environ={
            "K_SERVICE": "",
            "V2_RUNTIME_DATABASE_URL": "  ",
            "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE": "",
        },
        verifier_factory=factory,
    )

    assert factory.calls == 0


@pytest.mark.parametrize(
    "environ",
    [
        {"K_SERVICE": "policyengine-api"},
        {"V2_RUNTIME_DATABASE_URL": "postgresql+psycopg://configured"},
        {"V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE": V2_RUNTIME_SECRET_RESOURCE},
    ],
    ids=["cloud-run", "runtime-url", "runtime-secret"],
)
def test_a_selected_v2_runtime_database_is_checked_against_the_code_list(
    environ: dict[str, str],
) -> None:
    verifier = FakeCountryListVerifier()

    check_countries_table_at_startup(
        environ=environ, verifier_factory=CountingVerifierFactory(verifier)
    )

    assert verifier.verified_country_lists == [SUPPORTED_COUNTRY_IDS]


@pytest.mark.parametrize(
    "error",
    [
        CountryListMismatchError(listed_without_row=("us",), rows_not_listed=()),
        ProgrammingError(
            "SELECT countries.id FROM countries",
            {},
            Exception('relation "countries" does not exist'),
        ),
        ProgrammingError(
            "SELECT countries.id FROM countries",
            {},
            Exception("permission denied for table countries"),
        ),
    ],
    ids=["mismatch", "missing-table", "missing-privilege"],
)
def test_a_failed_check_stops_startup(error: Exception) -> None:
    verifier = FakeCountryListVerifier(error=error)

    with pytest.raises(type(error)):
        check_countries_table_at_startup(
            environ={"K_SERVICE": "policyengine-api"},
            verifier_factory=CountingVerifierFactory(verifier),
        )


@pytest.mark.parametrize(
    "message",
    [
        "V2_RUNTIME_DATABASE_URL must name a non-local Postgres host",
        "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE could not be resolved",
    ],
    ids=["invalid-url", "secret-unavailable"],
)
def test_unusable_v2_configuration_is_logged_and_left_to_readiness(
    message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Readiness already reports not ready for it, and recovers when it does."""

    def unusable_configuration() -> FakeCountryListVerifier:
        raise V2ConfigurationError(message)

    with caplog.at_level(logging.WARNING):
        check_countries_table_at_startup(
            environ={"K_SERVICE": "policyengine-api"},
            verifier_factory=unusable_configuration,
        )

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert message in caplog.records[0].getMessage()


@pytest.mark.parametrize(
    "error_type",
    [OperationalError, InterfaceError],
    ids=["operational", "interface"],
)
def test_an_unreachable_database_is_logged_and_startup_continues(
    error_type: type[OperationalError | InterfaceError],
    caplog: pytest.LogCaptureFixture,
) -> None:
    verifier = FakeCountryListVerifier(
        error=error_type(
            "SELECT countries.id FROM countries",
            {},
            Exception("connection to db.secret-host failed: password=hunter2"),
        )
    )

    with caplog.at_level(logging.WARNING):
        check_countries_table_at_startup(
            environ={"K_SERVICE": "policyengine-api"},
            verifier_factory=CountingVerifierFactory(verifier),
        )

    assert verifier.verified_country_lists == [SUPPORTED_COUNTRY_IDS]
    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    message = caplog.records[0].getMessage()
    assert "countries table" in message
    assert error_type.__name__ in message
    assert "secret-host" not in message
    assert "hunter2" not in message


def test_importing_the_asgi_application_runs_the_check(tmp_path: Path) -> None:
    """The check runs at import; an unusable v2 runtime URL is only logged."""
    environment = os.environ.copy()
    environment.update(
        {
            "POLICYENGINE_API_STARTUP_WARMUP": "0",
            "V2_RUNTIME_DATABASE_URL": (
                "postgresql+psycopg://runtime:hunter2@localhost:5432/postgres"
                "?sslmode=require"
            ),
            "V2_SUPABASE_PROJECT_REF": "abcdefghijklmnopqrst",
            "V2_SUPABASE_ENVIRONMENT": "test-startup",
        }
    )
    for name in ("V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE", "K_SERVICE"):
        environment.pop(name, None)

    result = subprocess.run(
        [sys.executable, "-c", "import policyengine_api.asgi"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    # The application's log handler writes structured records to stdout.
    output = result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
    assert "Skipped the countries table check" in output
    assert "V2_RUNTIME_DATABASE_URL must name a non-local Postgres host" in output
    assert "hunter2" not in output
