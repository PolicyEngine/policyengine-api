"""Database session lifetime management for the v2 household report service."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


class HouseholdReportDatabaseSession:
    """Open the read sessions the household report service uses.

    Reports themselves live in the Simulation Entrypoint; the Public API reads
    what each country supports and its catalog versions.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Use ``session_factory`` to open every session."""
        self._session_factory = session_factory

    @contextmanager
    def read(self) -> Iterator[Session]:
        """Yield a session for reads; nothing is committed."""
        with self._session_factory() as session:
            yield session
