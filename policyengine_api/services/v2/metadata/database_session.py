"""Database session lifetime management for v2 metadata services."""

from __future__ import annotations

from sqlmodel import Session


class MetadataDatabaseSession:
    """Own the request-scoped read session used by metadata services."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        return self._session

    @property
    def dialect_name(self) -> str:
        return self._session.get_bind().dialect.name

    def close(self) -> None:
        self._session.close()
