"""SQLAlchemy session ownership for the v1 persistence layer."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


T = TypeVar("T")


_v1_session_factories: dict[bool, sessionmaker[Session]] = {}


class _IndexedMappingRow(dict):
    """SQLite row compatible with both SQLAlchemy and legacy mapping callers."""

    def __init__(self, cursor, values):
        self._values = values
        super().__init__(
            (description[0], values[index])
            for index, description in enumerate(cursor.description)
        )

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def __iter__(self):
        return iter(self._values)


class SessionManager:
    """Own sessions and transaction boundaries without leaking either to callers."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.session_factory = build_session_factory(engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.session_factory.begin() as session:
            yield session

    def run_in_transaction(self, callback: Callable[[Session], T]) -> T:
        with self.session_factory.begin() as session:
            return callback(session)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return the canonical SQLAlchemy session factory for an engine."""

    return sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )


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


def build_v1_session_manager(*, local: bool = False) -> SessionManager:
    """Temporary bridge for callers not yet migrated to ``sessionmaker``."""

    return SessionManager(get_v1_engine(local=local))


def get_v1_engine(*, local: bool = False) -> Engine:
    """Return the process-owned engine selected by the v1 runtime."""

    from policyengine_api.data.data import database, local_database

    selected_database = local_database if local else database

    if selected_database.local:
        if hasattr(selected_database, "_connection"):
            selected_database._connection.row_factory = _IndexedMappingRow
            engine = create_engine(
                "sqlite+pysqlite://",
                creator=lambda: selected_database._connection,
                poolclass=StaticPool,
            )
            event.listen(
                engine.pool,
                "checkout",
                lambda connection, *_: setattr(
                    connection, "row_factory", _IndexedMappingRow
                ),
            )
            return engine
        return create_engine(f"sqlite+pysqlite:///{Path(selected_database.db_url)}")
    return selected_database.pool


def get_v1_session_factory(*, local: bool = False) -> sessionmaker[Session]:
    """Return one configured factory per process-owned v1 engine."""

    if local not in _v1_session_factories:
        _v1_session_factories[local] = build_session_factory(get_v1_engine(local=local))
    return _v1_session_factories[local]


def clear_v1_session_factories() -> None:
    """Forget cached factories after their process-owned engines are closed."""

    _v1_session_factories.clear()
