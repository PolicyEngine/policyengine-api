"""Build Alembic target metadata from the existing SQL initializer."""

from pathlib import Path
import sqlite3

from sqlalchemy import JSON, MetaData, create_engine


DEFAULT_SCHEMA_SQL = Path(__file__).with_name("initialise_local.sql")

JSON_COLUMN_NAMES = {
    "computed_household_json",
    "economy_json",
    "household_json",
    "options_json",
    "policy_json",
    "reform_impact_json",
    "report_spec_json",
    "report_spec_snapshot_json",
    "simulation_spec_json",
    "simulation_spec_snapshot_json",
    "tracer_output",
    "output",
}


def _normalize_reflected_metadata(metadata: MetaData) -> None:
    for table in metadata.tables.values():
        for column in table.columns:
            if column.name in JSON_COLUMN_NAMES:
                column.type = JSON()
            if column.primary_key:
                column.nullable = False
            if column.server_default is not None:
                default_arg = str(column.server_default.arg).strip().upper()
                if "NULL" in default_arg:
                    column.server_default = None


def build_metadata_from_sql(schema_sql_path: str | Path | None = None) -> MetaData:
    """Reflect SQL initializer DDL into SQLAlchemy metadata for autogenerate.

    API v1 still uses raw SQL rather than ORM models. This keeps Alembic's
    autogenerate path tied to the existing initializer instead of maintaining a
    second manually-authored schema definition.
    """

    schema_sql_path = Path(schema_sql_path or DEFAULT_SCHEMA_SQL)
    connection = sqlite3.connect(":memory:")
    connection.executescript(schema_sql_path.read_text())

    engine = create_engine("sqlite://", creator=lambda: connection)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    _normalize_reflected_metadata(metadata)
    return metadata
