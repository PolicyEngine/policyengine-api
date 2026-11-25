"""Stand-ins for the read-only Sessions the v2 migration qualification commands open.

Each command opens Session factories with ``session_factories(settings)``, reads
its counts in one Session, and closes it without committing, which rolls the
READ ONLY transaction back. ``QualificationSessions`` is such a
``session_factories``, handing out one ``CountingSession``.
``serve_read_only_sessions`` stands in for ``unpooled_v2_read_only_sessions``,
the commands' default, to check that they open it for the configured URL.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Self

from policyengine_api.data.v2 import database
from policyengine_api.data.v2.models import V2_TABLE_NAMES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    import pytest


class CountingSession:
    """A Session that answers each count with the next of ``counts``."""

    def __init__(self, counts: Iterable[int]) -> None:
        self._counts = iter(counts)
        self.statements: list[str] = []
        self.committed = False
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exception: object) -> None:
        # Session.close, which rolls back a transaction that wasn't committed.
        self.closed = True

    def scalar(self, statement: object) -> int:
        self.statements.append(str(statement))
        return next(self._counts)

    def commit(self) -> None:
        self.committed = True

    @property
    def rolled_back(self) -> bool:
        """Whether the session closed without committing its transaction."""
        return self.closed and not self.committed


class QualificationSessions:
    """Session factories that hand out ``session``, recording their settings."""

    def __init__(self, session: CountingSession) -> None:
        self.session = session
        self.opened_with: list[object] = []
        self.closed = False

    @contextmanager
    def __call__(self, settings: object) -> Iterator[Callable[[], CountingSession]]:
        self.opened_with.append(settings)
        try:
            yield lambda: self.session
        finally:
            # The engine is disposed of when the factories close.
            self.closed = True


def serve_public_tables(
    monkeypatch: pytest.MonkeyPatch,
    public_tables: Iterable[str] = V2_TABLE_NAMES,
) -> None:
    """Make every v2 schema Inspector list ``public_tables``."""
    tables = sorted(public_tables)
    monkeypatch.setattr(
        database,
        "v2_schema_inspector",
        lambda _session: SimpleNamespace(get_table_names=lambda schema: tables),
    )


def serve_read_only_sessions(
    monkeypatch: pytest.MonkeyPatch, sessions: QualificationSessions
) -> list[object]:
    """Stand in ``sessions`` for ``unpooled_v2_read_only_sessions``.

    Return the list of URLs it is opened for.
    """
    urls: list[object] = []

    def read_only_sessions(url: object) -> object:
        urls.append(url)
        return sessions(url)

    monkeypatch.setattr(database, "unpooled_v2_read_only_sessions", read_only_sessions)
    return urls
