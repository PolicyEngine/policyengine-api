"""SQLAlchemy session ownership for the v1 persistence layer."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


T = TypeVar("T")


class SessionManager:
    """Own sessions and transaction boundaries without leaking either to callers."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def run_in_transaction(self, callback: Callable[[Session], T]) -> T:
        with self.session() as session:
            try:
                result = callback(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise


def build_sqlite_session_manager(
    database_path: str | Path | None = None,
) -> SessionManager:
    """Build a SQLite manager for local execution or isolated tests."""

    if database_path is None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(f"sqlite+pysqlite:///{Path(database_path)}")
    return SessionManager(engine)
