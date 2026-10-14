"""Database session lifetime management for v2 metadata services."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlmodel import Session


class MetadataDatabaseSession:
    """Own the request-scoped read session used by metadata services."""

    def __init__(self, session: Session) -> None:
        """Wrap one request's session; the service reads through it until close."""
        self._session = session

    @property
    def session(self) -> Session:
        """The open request session that every metadata query runs on."""
        return self._session

    def close(self) -> None:
        """Close the request's session."""
        self._session.close()
