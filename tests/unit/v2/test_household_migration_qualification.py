"""Tests for read-only v2 household migration qualification."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from policyengine_api.data.v2 import household_migration_qualification as qualification
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
    def __init__(self, counts: tuple[int, int, int, int, int]) -> None:
        self._counts = iter(counts)
        self.transaction = FakeTransaction()
        self.statements: list[str] = []

    def begin(self) -> FakeTransaction:
        return self.transaction

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)

    def scalar(self, _statement: object) -> int:
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


def test_empty_target_is_qualified_in_a_rolled_back_read_only_transaction() -> None:
    connection = FakeConnection((0, 0, 0, 0, 0))
    engine = FakeEngine(connection)

    evidence = qualification.qualify_household_migration_target(
        ENVIRONMENT,
        engine_builder=lambda _settings: engine,
    )

    assert evidence.as_dict() == {
        "outcome": "ok",
        "qualification": "performed",
        "environment": "staging",
        "project_ref": "abcdefghijklmnopqrst",
        "counts": {
            "households": 0,
            "user_household_associations": 0,
            "simulation_household_references": 0,
            "report_household_references": 0,
            "household_jobs": 0,
        },
    }
    assert connection.statements == ["SET TRANSACTION READ ONLY"]
    assert connection.transaction.rolled_back
    assert engine.disposed


def test_applied_household_revision_skips_row_qualification() -> None:
    connection = FakeConnection((1, 2, 3, 4, 5))
    engine = FakeEngine(connection)

    evidence = qualification.qualify_household_migration_if_pending(
        ENVIRONMENT,
        engine_builder=lambda _settings: engine,
        pending_checker=lambda _connection: False,
    )

    assert evidence.required is False
    assert evidence.counts == qualification.HouseholdDataCounts(0, 0, 0, 0, 0)
    assert connection.transaction.rolled_back
    assert engine.disposed


def test_pending_household_revision_runs_row_qualification() -> None:
    connection = FakeConnection((0, 0, 0, 0, 0))
    engine = FakeEngine(connection)

    evidence = qualification.qualify_household_migration_if_pending(
        ENVIRONMENT,
        engine_builder=lambda _settings: engine,
        pending_checker=lambda _connection: True,
    )

    assert evidence.required is True
    assert connection.statements == ["SET TRANSACTION READ ONLY"]
    assert connection.transaction.rolled_back
    assert engine.disposed


@pytest.mark.parametrize(
    "counts",
    [
        (1, 0, 0, 0, 0),
        (0, 1, 0, 0, 0),
        (0, 0, 1, 0, 0),
        (0, 0, 0, 1, 0),
        (0, 0, 0, 0, 1),
        (1, 2, 3, 4, 5),
    ],
)
def test_retained_household_data_stops_without_committing(
    counts: tuple[int, int, int, int, int],
) -> None:
    connection = FakeConnection(counts)
    engine = FakeEngine(connection)

    with pytest.raises(
        qualification.RetainedHouseholdDataError,
        match="migration stopped without modifying data",
    ) as raised:
        qualification.qualify_household_migration_target(
            ENVIRONMENT,
            engine_builder=lambda _settings: engine,
        )

    assert raised.value.counts == qualification.HouseholdDataCounts(*counts)
    assert connection.transaction.rolled_back
    assert engine.disposed


def test_main_redacts_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> None:
        raise RuntimeError("postgresql://user:secret@private-host/database")

    monkeypatch.setattr(qualification, "qualify_household_migration_if_pending", fail)

    assert qualification.main() == 1
    captured = capsys.readouterr()
    assert "qualification failed unexpectedly" in captured.err
    assert "secret" not in captured.err
    assert "private-host" not in captured.err
