"""Safely inspect and upgrade the API v1 Cloud SQL schema.

Every mode runs in one ORM Session. Alembic's ``MigrationContext``,
``compare_metadata`` and ``command.upgrade`` take a Connection, so they get
the Session's own (rule api.data.orm-only names these exceptions); everything
else runs through the Session.
"""

from __future__ import annotations

import argparse
import os
from enum import StrEnum
from typing import TYPE_CHECKING

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select
from sqlalchemy.engine import URL

from policyengine_api.constants import REPO
from policyengine_api.data.orm import unpooled_v1_sessions, v1_schema_inspector
from policyengine_api.data.v1_models import V1Base

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

ALEMBIC_CONFIG = REPO / "alembic-v1.ini"
MIGRATION_LOCK_NAME = "policyengine-api-v1-alembic"
MIGRATION_LOCK_TIMEOUT_SECONDS = 60
DATABASE_NAME = "policyengine"
READONLY_USER = "policyengine_schema_reader"
MIGRATION_USER = "policyengine_schema_migrator"
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 3307
# Alembic's metadata differences: ("remove_table", table) and, for a column,
# (operation, schema, table, column, existing settings, old value, new value).
TABLE_DIFFERENCE_LENGTH = 2
COLUMN_DIFFERENCE_LENGTH = 7


class DatabaseState(StrEnum):
    """Where a v1 database stands against the Alembic revision scripts.

    UNVERSIONED has no version table and INVALID has an empty one; neither is
    ever stamped or upgraded automatically.
    """

    UNVERSIONED = "unversioned"
    INVALID = "invalid"
    PENDING = "pending"
    HEAD = "head"


def build_database_url(
    *,
    username: str,
    password: str,
    host: str,
    port: int,
    database: str,
) -> URL:
    """Build a SQLAlchemy URL without stringifying its credentials."""
    return URL.create(
        drivername="mysql+pymysql",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    )


def classify_database_state(
    *,
    version_table_exists: bool,
    current_heads: set[str],
    script_heads: set[str] | None = None,
) -> DatabaseState:
    """Classify a database by its version table and heads.

    Without ``script_heads`` a versioned database is reported as pending, never head.
    """
    if not version_table_exists:
        return DatabaseState.UNVERSIONED
    if not current_heads:
        return DatabaseState.INVALID
    if script_heads is not None and current_heads == script_heads:
        return DatabaseState.HEAD
    return DatabaseState.PENDING


def describe_metadata_difference(difference: object) -> str:
    """Return a stable, data-free description of an Alembic metadata diff."""
    item = difference
    if isinstance(item, list) and len(item) == 1:
        item = item[0]
    if not isinstance(item, tuple) or not item:
        msg = "Unsupported metadata difference shape"
        raise ValueError(msg)

    operation = item[0]
    if operation == "remove_table" and len(item) >= TABLE_DIFFERENCE_LENGTH:
        return f"extra_table:{item[1].name}"
    if operation == "modify_nullable" and len(item) >= COLUMN_DIFFERENCE_LENGTH:
        return (
            f"nullable:{item[2]}.{item[3]}:"
            f"{str(item[5]).lower()}->{str(item[6]).lower()}"
        )
    if operation == "modify_default" and len(item) >= COLUMN_DIFFERENCE_LENGTH:
        existing = "none" if item[5] is None else "present"
        target = "none" if item[6] is None else "present"
        return f"default:{item[2]}.{item[3]}:{existing}->{target}"
    msg = f"Unsupported metadata difference operation: {operation}"
    raise ValueError(msg)


def _config(session: Session) -> Config:
    """Return the v1 Alembic configuration, migrating the Session's connection."""
    config = Config(str(ALEMBIC_CONFIG))
    config.attributes["connection"] = session.connection()
    return config


def _script_heads(config: Config) -> set[str]:
    return set(ScriptDirectory.from_config(config).get_heads())


def database_state(session: Session) -> DatabaseState:
    """Return the database's Alembic state against the repository's revision heads."""
    inspector = v1_schema_inspector(session)
    version_table_exists = "alembic_version" in inspector.get_table_names()
    context = MigrationContext.configure(session.connection())
    config = _config(session)
    return classify_database_state(
        version_table_exists=version_table_exists,
        current_heads=set(context.get_current_heads()),
        script_heads=_script_heads(config),
    )


def metadata_differences(session: Session) -> set[str]:
    """Describe every difference between the live schema and the v1 models.

    Raise ValueError for a kind of difference that has no data-free description.
    """
    context = MigrationContext.configure(
        session.connection(),
        opts={"compare_type": True, "compare_server_default": True},
    )
    return {
        describe_metadata_difference(difference)
        for difference in compare_metadata(context, V1Base.metadata)
    }


def verify_head_schema(session: Session) -> None:
    """Raise RuntimeError unless the database is at the head with no schema drift."""
    state = database_state(session)
    if state is not DatabaseState.HEAD:
        msg = f"Database is not at the Alembic head; found {state}"
        raise RuntimeError(msg)
    differences = metadata_differences(session)
    if differences:
        msg = f"Database metadata drift remains after migration: {sorted(differences)}"
        raise RuntimeError(msg)


def _acquire_lock(session: Session) -> None:
    """Take MySQL's named migration lock, waiting up to 60 seconds for it."""
    acquired = session.scalar(
        select(func.GET_LOCK(MIGRATION_LOCK_NAME, MIGRATION_LOCK_TIMEOUT_SECONDS))
    )
    if acquired != 1:
        msg = "Could not acquire the v1 Alembic migration lock"
        raise RuntimeError(msg)


def _release_lock(session: Session) -> None:
    session.execute(select(func.RELEASE_LOCK(MIGRATION_LOCK_NAME)))


def upgrade_database(session: Session, *, backup_id: str) -> None:
    """Upgrade a versioned database to head under a MySQL named lock, then verify it.

    A database already at head is only verified, so ``backup_id`` is required
    only when an upgrade will actually run.
    """
    _acquire_lock(session)
    try:
        state = database_state(session)
        if state in {DatabaseState.UNVERSIONED, DatabaseState.INVALID}:
            msg = (
                "database has no valid Alembic revision; automatic baseline "
                "stamping is disabled"
            )
            raise RuntimeError(msg)
        if state is DatabaseState.HEAD:
            verify_head_schema(session)
            return
        if not backup_id.strip():
            msg = "A completed Cloud SQL backup ID is required"
            raise ValueError(msg)

        command.upgrade(_config(session), "head")
        verify_head_schema(session)
    finally:
        _release_lock(session)


def _database_target(mode: str) -> str | URL:
    url_env_name = (
        "STAGE7_EXISTING_DATABASE_URL"
        if mode in {"verify-head", "state"}
        else "ALEMBIC_DATABASE_URL"
    )
    if explicit_url := os.environ.get(url_env_name):
        return explicit_url

    readonly = mode in {"verify-head", "state"}
    password_env_name = (
        "POLICYENGINE_DB_READONLY_PASSWORD"
        if readonly
        else "POLICYENGINE_DB_MIGRATION_PASSWORD"
    )
    password = os.environ.get(password_env_name)
    if not password:
        msg = f"{url_env_name} or {password_env_name} is required"
        raise RuntimeError(msg)
    return build_database_url(
        username=READONLY_USER if readonly else MIGRATION_USER,
        password=password,
        host=PROXY_HOST,
        port=PROXY_PORT,
        database=DATABASE_NAME,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        required=True,
        choices=("state", "verify-head", "upgrade"),
    )
    parser.add_argument("--backup-id", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run one --mode against the v1 database: state, verify-head or upgrade.

    Unless a database URL is set, the read-only modes connect through the proxy
    as the schema reader and upgrade as the migrator, in one transaction.
    """
    args = _parse_args(argv)
    with unpooled_v1_sessions(_database_target(args.mode)) as sessions:
        # The upgrade commits its one transaction; the read-only modes' sessions
        # close without committing.
        session_context = sessions.begin() if args.mode == "upgrade" else sessions()
        with session_context as session:
            if args.mode == "state":
                print(database_state(session).value)
            elif args.mode == "verify-head":
                verify_head_schema(session)
            else:
                upgrade_database(session, backup_id=args.backup_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
