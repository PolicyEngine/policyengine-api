"""Database session lifetime management for v2 report reads."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


class StoredReportDatabaseSession:
    """Open the read sessions V2StoredReportService uses.

    The Public API only reads reports, their runs and results; the simulation
    service and its Modal workers write them.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Use ``session_factory`` to open every session."""
        self._session_factory = session_factory

    @contextmanager
    def read(self) -> Iterator[Session]:
        """Yield a session for reads; nothing is committed."""
        with self._session_factory() as session:
            yield session
