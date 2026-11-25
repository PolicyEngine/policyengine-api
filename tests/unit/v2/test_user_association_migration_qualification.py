"""Tests for read-only Stage 12A user-association qualification."""

from __future__ import annotations

import json

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from policyengine_api.constants import REPO
from policyengine_api.data.v2 import (
    user_association_migration_qualification as qualification,
)
from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
    load_v2_migration_database_settings,
)
from tests.unit.v2.qualification_sessions import (
    CountingSession,
    QualificationSessions,
    serve_public_tables,
    serve_read_only_sessions,
)

ENVIRONMENT = {
    V2_MIGRATION_DATABASE_URL: (
        "postgresql+psycopg://migration:test-password@db."
        "abcdefghijklmnopqrst.supabase.co/postgres?sslmode=require"
    ),
    V2_SUPABASE_PROJECT_REF: "abcdefghijklmnopqrst",
    V2_SUPABASE_ENVIRONMENT: "staging",
}


@pytest.fixture(autouse=True)
def _every_association_table_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    serve_public_tables(monkeypatch)


def _qualify(counts, *, pending: bool, monkeypatch: pytest.MonkeyPatch):
    session = CountingSession(counts)
    sessions = QualificationSessions(session)
    read_only_urls = serve_read_only_sessions(monkeypatch, sessions)
    evidence = qualification.qualify_user_association_migration(
        ENVIRONMENT,
        pending_checker=lambda _session: pending,
    )
    return evidence, session, sessions, read_only_urls


def test_counts_are_reported_from_a_read_only_rolled_back_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, session, sessions, read_only_urls = _qualify(
        (3, 2, 0, 0), pending=True, monkeypatch=monkeypatch
    )

    assert evidence.as_dict() == {
        "outcome": "ok",
        "revision": "fbb7488ebe8a",
        "migration_pending": True,
        "dormant_tables_empty": True,
        "environment": "staging",
        "project_ref": "abcdefghijklmnopqrst",
        "counts": {
            "user_policies": 3,
            "user_household_associations": 2,
            "user_simulation_associations": 0,
            "user_report_associations": 0,
        },
    }
    configured = load_v2_migration_database_settings(ENVIRONMENT)
    assert read_only_urls == [configured.connection.url]
    assert session.rolled_back
    assert sessions.closed
    assert len(session.statements) == 4
    assert all("count(*)" in statement for statement in session.statements)


def test_retained_dormant_rows_stop_a_pending_reshape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(qualification.RetainedDormantAssociationError) as error:
        _qualify((0, 0, 1, 2), pending=True, monkeypatch=monkeypatch)

    assert error.value.counts.dormant_total == 3


def test_applied_reshape_reports_rows_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, session, _sessions, _read_only_urls = _qualify(
        (0, 0, 5, 7), pending=False, monkeypatch=monkeypatch
    )

    assert evidence.as_dict()["dormant_tables_empty"] is False
    assert evidence.as_dict()["migration_pending"] is False
    assert session.rolled_back


def test_revision_constant_names_a_revision_in_the_v2_chain() -> None:
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))

    revision = script.get_revision(qualification.USER_ASSOCIATION_MIGRATION_REVISION)

    assert revision is not None
    assert revision.down_revision == "91af4fc8d8c1"


def test_main_redacts_unexpected_errors(monkeypatch, capsys) -> None:
    def fail():
        msg = "postgresql://user:secret@host/db"
        raise RuntimeError(msg)

    monkeypatch.setattr(qualification, "qualify_user_association_migration", fail)

    assert qualification.main() == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["outcome"] == "error"
    assert "secret" not in json.dumps(payload)
