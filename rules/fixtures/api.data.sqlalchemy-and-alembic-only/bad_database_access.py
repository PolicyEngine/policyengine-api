"""Proof fixture: a driver connection, a driver's socket and a schema change.

The rule must reject all three. Two mistakes are taken from this repository's
history: the Stage 12 provisioning script (removed in d8bd72191) opened
psycopg connections directly, and the local database bootstrap added in
6c7804100 created the v1 tables with metadata.create_all at runtime. The
third reads the socket beneath a pymysql connection, which only a declared
exception may do.
"""

import psycopg
from sqlalchemy import Engine

from policyengine_api.data.v1_models import V1Base


def read_current_role(connection_url: str) -> str:
    """Return the role the database authenticated, through a driver connection."""
    with psycopg.connect(connection_url) as connection:
        row = connection.execute("SELECT current_user").fetchone()
    if row is None:
        msg = "the database returned no current role"
        raise RuntimeError(msg)
    return str(row[0])


def bootstrap_tables(engine: Engine) -> None:
    """Create every v1 table when the application starts."""
    V1Base.metadata.create_all(engine)


def driver_socket_number(driver_connection: object) -> int | None:
    """Return the file descriptor of the socket beneath a pymysql connection."""
    sock = getattr(driver_connection, "_sock", None)
    return None if sock is None else sock.fileno()
