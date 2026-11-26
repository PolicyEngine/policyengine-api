"""Database session lifetime management for the policy copy split."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


class PolicyCopySplitDatabaseSession:
    """Open read sessions and transaction-scoped sessions for the split.

    The command builds it on read-only Session factories for its listing, so
    the database itself refuses any write there.
    """

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
