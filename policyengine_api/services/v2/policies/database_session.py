"""Database session lifetime management for v2 policy services."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session


class PolicyDatabaseSession:
    """Open read sessions and transaction-scoped sessions for policy services."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def read(self) -> Iterator[Session]:
        with self._session_factory() as session:
            yield session

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self._session_factory.begin() as session:
            yield session
