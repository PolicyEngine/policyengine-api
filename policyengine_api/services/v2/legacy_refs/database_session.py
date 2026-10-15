"""Short read-only v1 Cloud SQL sessions for reference checks."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


class LegacyReferenceDatabaseSession:
    """Open one v1 transaction that is always rolled back and closed."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def read(self) -> Iterator[Session]:
        with self._session_factory() as session:
            transaction = session.begin()
            try:
                yield session
            finally:
                transaction.rollback()
