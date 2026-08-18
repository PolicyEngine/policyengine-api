"""Alembic environment for the isolated API v2-alpha Postgres schema."""

from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool

from policyengine_api.data.v2.migration_target import (
    load_v2_alembic_settings,
    qualify_v2_connection,
    validate_v2_head_table_inventory,
)
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.table_inventory import validate_v2_table_inventory


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = load_v2_alembic_settings()
target_metadata = V2_METADATA
validate_v2_table_inventory(target_metadata.tables)
script = ScriptDirectory.from_config(config)


def _include_application_object(_object, name, type_, _reflected, _compare_to) -> bool:
    """Keep Alembic's own version table outside application drift."""

    return not (type_ == "table" and name == "alembic_version")


def _configure(connection) -> None:
    qualify_v2_connection(connection, settings)
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
        validate_v2_head_table_inventory(connection)


def run_migrations_offline() -> None:
    raise RuntimeError(
        "v2 migrations require an online connection so target identity and "
        "generated application-data before/after states can be verified"
    )


def run_migrations_online() -> None:
    provided_connection = config.attributes.get("connection")
    if provided_connection is not None:
        _configure(provided_connection)
        return

    engine = create_engine(settings.url, poolclass=pool.NullPool)
    try:
        # Persistent target qualification performs live reads before Alembic
        # enters its migration transaction. SQLAlchemy 2.x autobegins on
        # those reads, so the environment must own a committing transaction;
        # otherwise a standalone command closes the connection and silently
        # rolls the completed migration back.
        with engine.begin() as connection:
            _configure(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
