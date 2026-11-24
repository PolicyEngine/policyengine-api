"""API v1's Session factories for commands that run once.

A session-factory module of rule api.data.orm-only. Importing it has no side
effects. ``policyengine_api.data.orm``, the application's module, loads a
``.env`` file when imported and imports the Cloud SQL connector and the pool's
event listeners. A command such as the v1 schema migration runs only with the
environment its deploy script sets, so it takes its Session factories from
here. ``orm`` builds its own factories with ``build_session_factory``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine
    from sqlalchemy.engine import URL, Inspector


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return SQLAlchemy's standard configurable Session factory."""
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@contextmanager
def unpooled_v1_sessions(url: str | URL) -> Iterator[sessionmaker[Session]]:
    """Yield v1 Session factories for one command's work on the database at ``url``.

    For commands and scripts that run once, such as the household mirror
    command and the v1 schema migration. Their engine keeps no connection
    pool, so no connection outlives its Session, and is disposed of on exit.
    """
    engine = create_engine(url, poolclass=NullPool)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()


def v1_schema_inspector(source: Session | sessionmaker[Session]) -> Inspector:
    """Return SQLAlchemy's Inspector of the v1 database a Session or factory uses.

    A Session's Inspector reads the schema inside the Session's transaction.
    """
    bind = source.connection() if isinstance(source, Session) else source.kw["bind"]
    inspector: Inspector = inspect(bind)
    return inspector
