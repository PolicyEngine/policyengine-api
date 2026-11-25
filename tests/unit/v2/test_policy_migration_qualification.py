"""Tests for read-only v2 policy migration qualification."""

from __future__ import annotations

import pytest

from policyengine_api.data.v2 import policy_migration_qualification as qualification
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
def _every_policy_table_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    serve_public_tables(monkeypatch)


def _configured_url() -> object:
    return load_v2_migration_database_settings(ENVIRONMENT).connection.url


def test_empty_target_is_qualified_in_a_rolled_back_read_only_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CountingSession((0, 0, 0))
    sessions = QualificationSessions(session)
    read_only_urls = serve_read_only_sessions(monkeypatch, sessions)

    evidence = qualification.qualify_policy_migration_target(ENVIRONMENT)

    assert evidence.as_dict() == {
        "outcome": "ok",
        "qualification": "performed",
        "environment": "staging",
        "project_ref": "abcdefghijklmnopqrst",
        "counts": {
            "policies": 0,
            "policy_parameter_values": 0,
            "user_policies": 0,
        },
    }
    assert read_only_urls == [_configured_url()]
    assert session.rolled_back
    assert sessions.closed


def test_applied_policy_revision_skips_predecessor_row_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CountingSession((1, 2, 3))
    sessions = QualificationSessions(session)
    read_only_urls = serve_read_only_sessions(monkeypatch, sessions)

    evidence = qualification.qualify_policy_migration_if_pending(
        ENVIRONMENT,
        pending_checker=lambda _session: False,
    )

    assert evidence.as_dict() == {
        "outcome": "ok",
        "qualification": "not-required",
        "environment": "staging",
        "project_ref": "abcdefghijklmnopqrst",
        "counts": {
            "policies": 0,
            "policy_parameter_values": 0,
            "user_policies": 0,
        },
    }
    assert read_only_urls == [_configured_url()]
    assert session.statements == []
    assert session.rolled_back
    assert sessions.closed


def test_pending_policy_revision_runs_predecessor_row_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CountingSession((0, 0, 0))
    sessions = QualificationSessions(session)
    read_only_urls = serve_read_only_sessions(monkeypatch, sessions)

    evidence = qualification.qualify_policy_migration_if_pending(
        ENVIRONMENT,
        pending_checker=lambda _session: True,
    )

    assert evidence.required is True
    assert read_only_urls == [_configured_url()]
    assert len(session.statements) == 3
    assert session.rolled_back
    assert sessions.closed


@pytest.mark.parametrize(
    "counts",
    [
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 2, 3),
    ],
)
def test_retained_policy_data_stops_without_committing(
    counts: tuple[int, int, int],
) -> None:
    session = CountingSession(counts)
    sessions = QualificationSessions(session)

    with pytest.raises(
        qualification.RetainedPolicyDataError,
        match="migration stopped without modifying data",
    ) as raised:
        qualification.qualify_policy_migration_target(
            ENVIRONMENT,
            session_factories=sessions,
        )

    assert raised.value.counts == qualification.PolicyDataCounts(*counts)
    assert session.rolled_back
    assert sessions.closed


def test_main_redacts_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> None:
        msg = "postgresql://user:secret@private-host/database"
        raise RuntimeError(msg)

    monkeypatch.setattr(qualification, "qualify_policy_migration_if_pending", fail)

    assert qualification.main() == 1
    captured = capsys.readouterr()
    assert "qualification failed unexpectedly" in captured.err
    assert "secret" not in captured.err
    assert "private-host" not in captured.err
