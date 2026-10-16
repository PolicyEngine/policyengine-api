"""Database session lifetime management for temporary comparison-run records."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


class ComparisonRunDatabaseSession:
    """Session lifetimes for comparison-run services: reads and transactions."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Open every session from session_factory."""
        self._session_factory = session_factory

    @contextmanager
    def read(self) -> Iterator[Session]:
        """Yield a session for reads that is closed, not committed, on exit."""
        with self._session_factory() as session:
            yield session

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Yield a session in a transaction that commits on success, else rolls back."""
        with self._session_factory.begin() as session:
            yield session
