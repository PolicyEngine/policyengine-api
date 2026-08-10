"""Exercise the complete Alembic lifecycle against an ephemeral MySQL schema."""

import os

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from policyengine_api.constants import REPO
from policyengine_api.data.v1_models import V1Base


def _ephemeral_mysql_url() -> str:
    database_url = os.environ.get("ALEMBIC_DATABASE_URL", "")
    if not database_url:
        pytest.skip("ALEMBIC_DATABASE_URL is not set")

    url = make_url(database_url)
    if url.get_backend_name() != "mysql":
        pytest.fail("ALEMBIC_DATABASE_URL must use MySQL for this test")
    if url.host not in {"127.0.0.1", "localhost"}:
        pytest.fail("Alembic lifecycle tests may only target local MySQL")
    if url.database != "policyengine_alembic_test":
        pytest.fail(
            "Alembic lifecycle tests require the policyengine_alembic_test schema"
        )
    return database_url


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_fresh_upgrade_check_downgrade_and_reupgrade():
    database_url = _ephemeral_mysql_url()
    config = _alembic_config(database_url)
    engine = create_engine(database_url)

    try:
        command.upgrade(config, "head")
        command.check(config)

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() is not None
            assert compare_metadata(context, V1Base.metadata) == []

        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}

        command.upgrade(config, "head")
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() is not None
            assert compare_metadata(context, V1Base.metadata) == []
    finally:
        engine.dispose()
