"""Temporary SQLAlchemy schema bootstrap for the local SQLite cache.

The production ``policy`` table has an autoincrementing column inside a
composite primary key. SQLite only autoincrements an ``INTEGER PRIMARY KEY``
column when it is the sole primary-key column, so the local cache has always
used ``policy.id`` as its database primary key. Keep that one physical-schema
exception explicit while deriving every other local table from the production
ORM metadata.
"""

from __future__ import annotations

from sqlalchemy import Column, Engine, Integer, JSON, MetaData, String, Table

from policyengine_api.data.local_models import LocalV1Base
from policyengine_api.data.v1_models import Policy, V1Base


_sqlite_policy_metadata = MetaData()
Table(
    Policy.__tablename__,
    _sqlite_policy_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("country_id", String(3), nullable=False),
    Column("label", String(255)),
    Column("api_version", String(10), nullable=False),
    Column("policy_json", JSON, nullable=False),
    Column("policy_hash", String(255), nullable=False),
)


def create_local_v1_schema(engine: Engine) -> None:
    """Create the temporary local schema through SQLAlchemy DDL constructs."""

    if engine.dialect.name != "sqlite":
        raise ValueError("The local v1 schema is only defined for SQLite")

    production_tables = [
        table
        for table in V1Base.metadata.sorted_tables
        if table is not Policy.__table__
    ]
    V1Base.metadata.create_all(engine, tables=production_tables)
    LocalV1Base.metadata.create_all(engine)
    _sqlite_policy_metadata.create_all(engine)
