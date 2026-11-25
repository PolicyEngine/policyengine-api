"""The disposable Postgres target and Alembic config of the v2 lifecycle tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alembic.config import Config

from policyengine_api.constants import REPO
from tests.fixtures.database_sessions import schema_inspector

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import ReflectedColumn
    from sqlalchemy.orm import Session, sessionmaker


def alembic_v2_config() -> Config:
    return Config(str(REPO / "alembic-v2.ini"))


def table_columns(
    source: Session | sessionmaker[Any], table_name: str
) -> dict[str, ReflectedColumn]:
    """Return a public table's columns by name, as the database describes them.

    ``source`` is a Session, read inside its transaction, or a Session factory
    (see ``schema_inspector``).
    """
    return {
        column["name"]: column
        for column in schema_inspector(source).get_columns(table_name, schema="public")
    }
