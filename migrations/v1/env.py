"""Alembic environment for the API v1 schema."""

from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from policyengine_api.data.v1_models import V1Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("ALEMBIC_DATABASE_URL") or config.get_main_option(
    "sqlalchemy.url"
)
if not database_url:
    raise RuntimeError(
        "ALEMBIC_DATABASE_URL is required; the local SQLite cache is not an "
        "Alembic migration target"
    )
if make_url(database_url).get_backend_name() != "mysql":
    raise RuntimeError("Alembic migrations must target a MySQL database")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = V1Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    provided_connection = config.attributes.get("connection")
    if provided_connection is not None:
        _run_migrations_with_connection(provided_connection)
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_migrations_with_connection(connection)


def _run_migrations_with_connection(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
