"""Shared fixtures for destructive Stage 7 tests on disposable MySQL only."""

from collections.abc import Iterator

from alembic.config import Config
import pytest
from sqlalchemy import Engine, create_engine, inspect

from policyengine_api.constants import REPO
from policyengine_api.data.v1_models import V1Base
from policyengine_api.scripts.stage7_database import assert_safe_toy_database_url


def stage7_database_url() -> str | None:
    import os

    return os.environ.get("STAGE7_TOY_DATABASE_URL")


def alembic_config(database_url: str) -> Config:
    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def reset_toy_database(engine: Engine, database_url: str) -> None:
    assert_safe_toy_database_url(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        for table_name in reversed(V1Base.metadata.sorted_tables):
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS `{table_name.name}`")
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")


def create_pre_alembic_schema(engine: Engine) -> None:
    """Create the existing schema from its independent legacy SQL source."""

    source = (REPO / "tests/fixtures/stage7_pre_alembic_schema.sql").read_text(
        encoding="utf-8"
    )
    statements = source.split(";")
    with engine.begin() as connection:
        for statement in statements:
            if statement.strip():
                connection.exec_driver_sql(statement.strip().removesuffix(";"))


def schema_signature(engine: Engine) -> dict:
    inspector = inspect(engine)

    def normalized(value):
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [normalized(item) for item in value]
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        return str(value)

    return {
        table_name: normalized(
            {
                "columns": inspector.get_columns(table_name),
                "indexes": inspector.get_indexes(table_name),
                "pk": inspector.get_pk_constraint(table_name),
                "unique": inspector.get_unique_constraints(table_name),
            }
        )
        for table_name in inspector.get_table_names()
    }


@pytest.fixture
def stage7_mysql() -> Iterator[tuple[str, Engine]]:
    database_url = stage7_database_url()
    if database_url is None:
        pytest.skip("STAGE7_TOY_DATABASE_URL is required for the MySQL probe")
    assert_safe_toy_database_url(database_url)
    engine = create_engine(database_url)
    reset_toy_database(engine, database_url)
    try:
        yield database_url, engine
    finally:
        reset_toy_database(engine, database_url)
        engine.dispose()
