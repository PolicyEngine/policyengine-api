"""Tests for read-only Stage 12A user-association qualification."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json

import pytest

from policyengine_api.data.v2 import (
    user_association_migration_qualification as qualification,
)
from alembic.config import Config
from alembic.script import ScriptDirectory

from policyengine_api.constants import REPO
from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
)


ENVIRONMENT = {
    V2_MIGRATION_DATABASE_URL: (
        "postgresql+psycopg://migration:test-password@db."
        "abcdefghijklmnopqrst.supabase.co/postgres?sslmode=require"
    ),
    V2_SUPABASE_PROJECT_REF: "abcdefghijklmnopqrst",
    V2_SUPABASE_ENVIRONMENT: "staging",
}


class FakeTransaction:
    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


class FakeConnection:
    def __init__(self, counts: tuple[int, int, int, int]) -> None:
        self._counts = iter(counts)
        self.transaction = FakeTransaction()
        self.options: list[dict[str, object]] = []
        self.statements: list[str] = []

    def execution_options(self, **options: object) -> "FakeConnection":
        self.options.append(options)
        return self

    def begin(self) -> FakeTransaction:
        return self.transaction

    def scalar(self, statement: object) -> int:
        self.statements.append(str(statement))
        return next(self._counts)


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.disposed = False

    @contextmanager
    def connect(self) -> Iterator[FakeConnection]:
        yield self.connection

    def dispose(self) -> None:
        self.disposed = True


def _qualify(counts, *, pending: bool):
    connection = FakeConnection(counts)
    engine = FakeEngine(connection)
    evidence = qualification.qualify_user_association_migration(
        ENVIRONMENT,
        engine_builder=lambda _settings: engine,
        pending_checker=lambda _connection: pending,
    )
    return evidence, connection, engine


def test_counts_are_reported_from_a_read_only_rolled_back_transaction() -> None:
    evidence, connection, engine = _qualify((3, 2, 0, 0), pending=True)

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
    assert connection.options == [{"postgresql_readonly": True}]
    assert connection.transaction.rolled_back
    assert engine.disposed
    assert len(connection.statements) == 4
    assert all("count(*)" in statement for statement in connection.statements)


def test_retained_dormant_rows_stop_a_pending_reshape() -> None:
    with pytest.raises(qualification.RetainedDormantAssociationError) as error:
        _qualify((0, 0, 1, 2), pending=True)

    assert error.value.counts.dormant_total == 3


def test_applied_reshape_reports_rows_without_failing() -> None:
    evidence, connection, _engine = _qualify((0, 0, 5, 7), pending=False)

    assert evidence.as_dict()["dormant_tables_empty"] is False
    assert evidence.as_dict()["migration_pending"] is False
    assert connection.transaction.rolled_back


def test_revision_constant_names_a_revision_in_the_v2_chain() -> None:
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic-v2.ini")))

    revision = script.get_revision(qualification.USER_ASSOCIATION_MIGRATION_REVISION)

    assert revision is not None
    assert revision.down_revision == "91af4fc8d8c1"


def test_main_redacts_unexpected_errors(monkeypatch, capsys) -> None:
    def fail():
        raise RuntimeError("postgresql://user:secret@host/db")

    monkeypatch.setattr(qualification, "qualify_user_association_migration", fail)

    assert qualification.main() == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["outcome"] == "error"
    assert "secret" not in json.dumps(payload)
