"""Alembic environment for PolicyEngine API v1 raw-SQL schema migrations."""

from logging.config import fileConfig
import importlib.util
import os
from pathlib import Path
import sys

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, str(Path(__file__).parent.parent))

metadata_path = (
    Path(__file__).parent.parent / "policyengine_api" / "data" / "alembic_metadata.py"
)
metadata_spec = importlib.util.spec_from_file_location(
    "policyengine_api_alembic_metadata",
    metadata_path,
)
if metadata_spec is None or metadata_spec.loader is None:
    raise RuntimeError(f"Could not load Alembic metadata helper from {metadata_path}")
metadata_module = importlib.util.module_from_spec(metadata_spec)
metadata_spec.loader.exec_module(metadata_module)
build_metadata_from_sql = metadata_module.build_metadata_from_sql


config = context.config

database_url = os.environ.get("POLICYENGINE_ALEMBIC_DATABASE_URL") or os.environ.get(
    "DATABASE_URL"
)
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

schema_sql_path = os.environ.get("POLICYENGINE_ALEMBIC_SCHEMA_SQL")
target_metadata = build_metadata_from_sql(schema_sql_path)


def _configure_context(connection=None, url: str | None = None) -> None:
    options = {
        "target_metadata": target_metadata,
        "compare_type": False,
        "compare_server_default": False,
    }
    if connection is not None:
        context.configure(connection=connection, **options)
    else:
        context.configure(
            url=url,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            **options,
        )


def run_migrations_offline() -> None:
    _configure_context(url=config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _configure_context(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
