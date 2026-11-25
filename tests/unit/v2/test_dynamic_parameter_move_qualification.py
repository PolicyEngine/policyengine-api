"""The read-only check that runs before C1 · 50's revision moves dynamic parameters.

While revision 7f7335f0eb31 is pending, the seed workflow counts the policy
values that name a dynamic parameter, in one READ ONLY transaction, and stops
before the schema upgrade while there are any. The revision refuses the same
rows itself; this step stops the deploy before Alembic runs at all.
"""

from __future__ import annotations

import json

import pytest

from policyengine_api.data.v2 import dynamic_parameter_move_qualification as move
from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
    load_v2_migration_database_settings,
)
from tests.unit.v2.qualification_sessions import (
    CountingSession,
    QualificationSessions,
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


def test_the_check_belongs_to_the_dynamic_parameter_tables_revision() -> None:
    assert move.DYNAMIC_PARAMETER_TABLES_REVISION == "7f7335f0eb31"


def test_a_pending_move_with_no_such_value_is_qualified_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CountingSession((0,))
    sessions = QualificationSessions(session)
    read_only_urls = serve_read_only_sessions(monkeypatch, sessions)

    evidence = move.qualify_dynamic_parameter_move_if_pending(
        ENVIRONMENT, pending_checker=lambda _session: True
    )

    assert evidence.as_dict() == {
        "outcome": "ok",
        "qualification": "performed",
        "environment": "staging",
        "project_ref": "abcdefghijklmnopqrst",
        "counts": {"policy_values_naming_dynamic_parameters": 0},
    }
    assert read_only_urls == [
        load_v2_migration_database_settings(ENVIRONMENT).connection.url
    ]
    assert len(session.statements) == 1
    assert "starts_with" in session.statements[0]
    assert session.rolled_back
    assert sessions.closed


def test_an_applied_move_reads_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    session = CountingSession((5,))
    sessions = QualificationSessions(session)
    serve_read_only_sessions(monkeypatch, sessions)

    evidence = move.qualify_dynamic_parameter_move_if_pending(
        ENVIRONMENT, pending_checker=lambda _session: False
    )

    assert evidence.as_dict()["qualification"] == "not-required"
    assert evidence.as_dict()["counts"] == {
        "policy_values_naming_dynamic_parameters": 0
    }
    assert session.statements == []
    assert session.rolled_back


@pytest.mark.parametrize("count", [1, 13])
def test_policy_values_naming_dynamic_parameters_stop_the_deploy(count: int) -> None:
    session = CountingSession((count,))
    sessions = QualificationSessions(session)

    with pytest.raises(
        move.PolicyValuesNameDynamicParametersError,
        match=f"{count} policy values? names? (a )?dynamic parameters?",
    ) as raised:
        move.qualify_dynamic_parameter_move_if_pending(
            ENVIRONMENT,
            session_factories=sessions,
            pending_checker=lambda _session: True,
        )

    assert raised.value.count == count
    assert "C1 · 49" in str(raised.value)
    assert session.rolled_back


def test_main_prints_the_refusal_and_redacts_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse() -> None:
        raise move.PolicyValuesNameDynamicParametersError(2)

    monkeypatch.setattr(move, "qualify_dynamic_parameter_move_if_pending", refuse)
    assert move.main() == 1
    refusal = json.loads(capsys.readouterr().err)
    assert refusal["error"]["type"] == "PolicyValuesNameDynamicParametersError"
    assert "2 policy values" in refusal["error"]["message"]

    def fail() -> None:
        msg = "postgresql://user:secret@private-host/database"
        raise RuntimeError(msg)

    monkeypatch.setattr(move, "qualify_dynamic_parameter_move_if_pending", fail)
    assert move.main() == 1
    captured = capsys.readouterr()
    assert "qualification failed unexpectedly" in captured.err
    assert "secret" not in captured.err
    assert "private-host" not in captured.err
