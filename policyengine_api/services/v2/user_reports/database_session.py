"""Database session lifetime management for v2 user-report services."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


class UserReportDatabaseSession:
    """Open read sessions and transactions for user-report services."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Use ``session_factory`` to open every session."""
        self._session_factory = session_factory

    @contextmanager
    def read(self) -> Iterator[Session]:
        """Yield a session for reads; nothing is committed."""
        with self._session_factory() as session:
            yield session

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Yield a session whose transaction commits on exit and rolls back on error."""
        with self._session_factory.begin() as session:
            yield session
