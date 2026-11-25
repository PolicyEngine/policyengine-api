"""The split gives way to API v1's live writes: a copy that waits too long is retried.

The command's lock timeout (500 ms) is shorter than PostgreSQL's default
one-second deadlock_timeout, so in a lock cycle with a live write the
split's wait ends first. The service then rolls back that copy's
transaction and tries it again, so the live write goes ahead.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID

import psycopg.errors
import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.services.v2.policy_copy_split import services
from policyengine_api.services.v2.policy_copy_split.services import (
    V2PolicyCopySplitService,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

COPY_ID = UUID("00000000-0000-0000-0000-0000000d0001")
SPLIT_RESULT = object()


class RecordingDatabaseSession:
    """Count the transactions the service opens; each yields a stand-in session."""

    def __init__(self) -> None:
        self.transactions = 0

    @contextmanager
    def read(self) -> Iterator[object]:
        yield object()

    @contextmanager
    def transaction(self) -> Iterator[object]:
        self.transactions += 1
        yield object()


def _lock_error(error_type: type[Exception]) -> OperationalError:
    return OperationalError("SELECT 1", {}, error_type("waited too long"))


@pytest.fixture
def one_copy(monkeypatch) -> None:
    monkeypatch.setattr(services, "read_policy_copy_ids", lambda _session: (COPY_ID,))


def _split_failing(monkeypatch, *errors: Exception) -> list[UUID]:
    """Make each copy's split raise ``errors`` in turn, then succeed."""
    remaining_errors = list(errors)
    attempts: list[UUID] = []

    def split(_session: object, policy_id: UUID) -> object:
        attempts.append(policy_id)
        if remaining_errors:
            raise remaining_errors.pop(0)
        return SPLIT_RESULT

    monkeypatch.setattr(services, "split_policy_copy_in_session", split)
    return attempts


@pytest.mark.usefixtures("one_copy")
@pytest.mark.parametrize(
    "error_type",
    [psycopg.errors.LockNotAvailable, psycopg.errors.DeadlockDetected],
)
def test_a_copy_that_meets_a_lock_conflict_is_tried_again(
    monkeypatch, error_type: type[Exception]
) -> None:
    attempts = _split_failing(monkeypatch, _lock_error(error_type))
    database_session = RecordingDatabaseSession()
    waits: list[float] = []
    service = V2PolicyCopySplitService(
        database_session, retry_delay_seconds=0.25, sleep=waits.append
    )

    assert list(service.split_policy_copies()) == [SPLIT_RESULT]
    assert attempts == [COPY_ID, COPY_ID]
    assert database_session.transactions == 2
    assert waits == [0.25]


@pytest.mark.usefixtures("one_copy")
def test_a_copy_still_in_conflict_after_every_attempt_fails_the_run(
    monkeypatch,
) -> None:
    lock_errors = [_lock_error(psycopg.errors.LockNotAvailable) for _ in range(3)]
    attempts = _split_failing(monkeypatch, *lock_errors)
    service = V2PolicyCopySplitService(
        RecordingDatabaseSession(), attempts=3, sleep=lambda _seconds: None
    )

    with pytest.raises(OperationalError, match="waited too long"):
        list(service.split_policy_copies())
    assert attempts == [COPY_ID] * 3


@pytest.mark.usefixtures("one_copy")
def test_another_database_error_is_not_retried(monkeypatch) -> None:
    attempts = _split_failing(monkeypatch, _lock_error(psycopg.errors.UndefinedTable))
    service = V2PolicyCopySplitService(
        RecordingDatabaseSession(), sleep=lambda _seconds: None
    )

    with pytest.raises(OperationalError):
        list(service.split_policy_copies())
    assert attempts == [COPY_ID]
