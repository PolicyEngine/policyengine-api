"""Alembic environment for the isolated API v2-alpha Postgres schema."""

from __future__ import annotations

from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool
from sqlmodel import Session

from policyengine_api.data.v2.migration_target import (
    load_v2_alembic_settings,
    qualify_v2_target,
    validate_v2_head_schema,
)
from policyengine_api.data.v2.models import V2_METADATA, V2_TABLE_NAMES

if TYPE_CHECKING:
    from alembic.runtime.environment import NameFilterType
    from sqlalchemy import Connection
    from sqlalchemy.sql.schema import SchemaItem

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = load_v2_alembic_settings()
target_metadata = V2_METADATA
script = ScriptDirectory.from_config(config)


def _include_application_object(
    _object: SchemaItem,
    name: str | None,
    type_: NameFilterType,
    _reflected: bool,  # noqa: FBT001  # Alembic calls include_object with positional arguments
    _compare_to: SchemaItem | None,
) -> bool:
    """Keep Alembic's own version table outside application drift."""
    return not (type_ == "table" and name == "alembic_version")


def _configure(connection: Connection) -> None:
    # Inside run_migrations_online's engine.begin(), each Session joins that
    # transaction, and closing it leaves the transaction to the environment.
    # On a connection passed in with no transaction open, a Session begins
    # its own, and closing it rolls that transaction back.
    with Session(bind=connection) as session:
        qualify_v2_target(session, settings)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        include_object=_include_application_object,
        version_table="alembic_version",
        version_table_schema="public",
    )
    migration_context = context.get_context()
    previous_heads = frozenset(migration_context.get_current_heads())
    with context.begin_transaction():
        context.run_migrations()
    current_heads = frozenset(migration_context.get_current_heads())
    script_heads = frozenset(script.get_heads())
    if current_heads != previous_heads and current_heads == script_heads:
        with Session(bind=connection) as session:
            validate_v2_head_schema(session, V2_TABLE_NAMES)


def run_migrations_offline() -> None:
    """Raise, because v2 migrations need a live connection to qualify the target."""
    msg = (
        "v2 migrations require an online connection so target identity and "
        "generated application-data before/after states can be verified"
    )
    raise RuntimeError(msg)


def run_migrations_online() -> None:
    """Migrate the caller's connection, or else a new engine in one transaction.

    On a new engine, the target qualification, the migration and, when the
    migration reaches the script heads, the head schema check share one
    transaction, which commits only when all of them succeed: a failed
    ``validate_v2_head_schema`` rolls the migration back.
    """
    provided_connection = config.attributes.get("connection")
    if provided_connection is not None:
        _configure(provided_connection)
        return

    engine = create_engine(settings.url, poolclass=pool.NullPool)
    try:
        # engine.begin() opens the one transaction the qualification's reads,
        # the migration and validate_v2_head_schema run in. Alembic's
        # begin_transaction joins it rather than committing on its own.
        # _configure runs the head schema check only when the migration moved
        # the database to the script heads: then the migration commits only
        # when the check passes, and engine.begin() rolls it back when the
        # check raises. Any other migration commits once it completes.
        with engine.begin() as connection:
            _configure(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
