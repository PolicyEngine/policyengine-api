"""The disposable Postgres target and Alembic config of the v2 lifecycle tests."""

import os
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy.engine.interfaces import ReflectedColumn

from policyengine_api.constants import REPO
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from tests.fixtures.database_sessions import schema_inspector


def disposable_v2_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(V2_ALEMBIC_DISPOSABLE_TEST, ""),
        }
    )
    if not settings.disposable_test:
        pytest.fail("v2 lifecycle tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


def alembic_v2_config() -> Config:
    return Config(str(REPO / "alembic-v2.ini"))


def table_columns(source: Any, table_name: str) -> dict[str, ReflectedColumn]:
    """Return a public table's columns by name, as the database describes them.

    ``source`` is a Session or a Session factory (see ``schema_inspector``).
    """
    return {
        column["name"]: column
        for column in schema_inspector(source).get_columns(table_name, schema="public")
    }
