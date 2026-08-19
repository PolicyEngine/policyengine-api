"""SQLite-only v1 schema helper confined to explicit test fixtures."""

from sqlalchemy import Column, Engine, Integer, JSON, MetaData, String, Table

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


def create_test_v1_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        raise ValueError("the test-only v1 schema helper requires SQLite")
    V1Base.metadata.create_all(
        engine,
        tables=[
            table
            for table in V1Base.metadata.sorted_tables
            if table is not Policy.__table__
        ],
    )
    _sqlite_policy_metadata.create_all(engine)
