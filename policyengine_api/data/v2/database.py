"""Lazy, process-owned SQLModel engine and Session configuration for API v2."""

from __future__ import annotations

import atexit
import os
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_runtime_database_settings,
)

if TYPE_CHECKING:
    from sqlalchemy import Engine

DATABASE_POOL_RECYCLE_SECONDS = 1800
DATABASE_POOL_SIZE = 5
DATABASE_POOL_MAX_OVERFLOW = 5
DATABASE_TIMEOUT_SECONDS = 5


@dataclass
class _V2EngineState:
    """The process-owned v2 engine and Session factories.

    ``engine_pid`` is the ID of the process that created the engine, and
    ``engine_url_fingerprint`` identifies its target. ``_state_lock`` guards
    every field, and a forked child discards the state it inherits.
    """

    engine: Engine | None = None
    engine_pid: int | None = None
    engine_url_fingerprint: tuple[object, ...] | None = None
    session_factory: sessionmaker[Session] | None = None
    read_session_factory: sessionmaker[Session] | None = None


_state_lock = Lock()
_engine_state = _V2EngineState()


def _url_fingerprint(settings: V2DatabaseSettings) -> tuple[object, ...]:
    """Build a private comparison value that is never rendered or logged."""
    url = settings.connection.url
    return (
        url.drivername,
        url.username,
        url.password,
        url.host,
        url.port,
        url.database,
        tuple(sorted(url.query.items())),
        settings.target.project_ref,
        settings.target.environment,
    )


def build_v2_engine(settings: V2DatabaseSettings) -> Engine:
    """Construct an unconnected SQLModel engine for an explicit v2 target."""
    return create_engine(
        settings.connection.url,
        pool_pre_ping=True,
        pool_recycle=DATABASE_POOL_RECYCLE_SECONDS,
        pool_size=DATABASE_POOL_SIZE,
        max_overflow=DATABASE_POOL_MAX_OVERFLOW,
        pool_timeout=DATABASE_TIMEOUT_SECONDS,
        connect_args={
            "connect_timeout": DATABASE_TIMEOUT_SECONDS,
            "options": (f"-c statement_timeout={DATABASE_TIMEOUT_SECONDS * 1_000}"),
        },
    )


def build_v2_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a factory whose ordinary sessions are SQLModel Sessions."""
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


class ReadOnlySessionError(RuntimeError):
    """Raised when code tries to write rows through a v2 read session."""


def _refuse_flush(*_flush_arguments: object) -> None:
    msg = "v2 read sessions do not write rows"
    raise ReadOnlySessionError(msg)


def build_v2_read_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a factory of Sessions for v2 metadata reads, run without a transaction.

    The sessions share ``engine``'s pool in autocommit mode, so psycopg sends
    each statement on its own: no BEGIN before the first read and no ROLLBACK
    when the session closes. Only the metadata reader uses them: each of its
    reads is one statement on a published catalog version, which never
    changes, so no common snapshot is needed. The sessions refuse to flush
    added or changed rows; statements passed directly to ``execute`` are not
    checked, so they must stay reads. The pool restores the ordinary mode
    when a connection returns.
    """
    factory = sessionmaker(
        bind=engine.execution_options(isolation_level="AUTOCOMMIT"),
        class_=Session,
        expire_on_commit=False,
    )
    event.listen(factory, "before_flush", _refuse_flush)
    return factory


def _discard_inherited_state(current_pid: int) -> None:
    """Drop pool state inherited through a process fork without touching parent FDs."""
    if _engine_state.engine is not None:
        _engine_state.engine.dispose(close=False)
    _engine_state.engine = None
    _engine_state.engine_pid = current_pid
    _engine_state.engine_url_fingerprint = None
    _engine_state.session_factory = None
    _engine_state.read_session_factory = None


def get_v2_engine(settings: V2DatabaseSettings | None = None) -> Engine:
    """Return the one lazy v2 runtime engine owned by this process."""
    current_pid = os.getpid()
    with _state_lock:
        if (
            _engine_state.engine_pid is not None
            and _engine_state.engine_pid != current_pid
        ):
            _discard_inherited_state(current_pid)

        selected_settings = settings or load_v2_runtime_database_settings()
        fingerprint = _url_fingerprint(selected_settings)
        if _engine_state.engine is not None:
            if fingerprint != _engine_state.engine_url_fingerprint:
                msg = (
                    "the process-owned v2 engine is already bound to a different "
                    "explicit target"
                )
                raise V2ConfigurationError(msg)
            return _engine_state.engine

        _engine_state.engine = build_v2_engine(selected_settings)
        _engine_state.engine_pid = current_pid
        _engine_state.engine_url_fingerprint = fingerprint
        return _engine_state.engine


def get_v2_session_factory(
    settings: V2DatabaseSettings | None = None,
) -> sessionmaker[Session]:
    """Return the process-owned SQLModel Session factory without opening a session."""
    engine = get_v2_engine(settings)
    with _state_lock:
        if _engine_state.session_factory is None:
            _engine_state.session_factory = build_v2_session_factory(engine)
        return _engine_state.session_factory


def get_v2_read_session_factory(
    settings: V2DatabaseSettings | None = None,
) -> sessionmaker[Session]:
    """Return the process-owned read-only Session factory without opening one.

    See ``build_v2_read_session_factory``.
    """
    engine = get_v2_engine(settings)
    with _state_lock:
        if _engine_state.read_session_factory is None:
            _engine_state.read_session_factory = build_v2_read_session_factory(engine)
        return _engine_state.read_session_factory


def close_v2_database() -> None:
    """Dispose this process's v2 pool and forget its lazy configuration."""
    with _state_lock:
        if _engine_state.engine is not None:
            _engine_state.engine.dispose()
        _engine_state.engine = None
        _engine_state.engine_pid = None
        _engine_state.engine_url_fingerprint = None
        _engine_state.session_factory = None
        _engine_state.read_session_factory = None


atexit.register(close_v2_database)
