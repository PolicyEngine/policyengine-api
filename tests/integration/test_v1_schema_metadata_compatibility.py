"""Compare ORM metadata with an existing v1 schema without mutating it."""

import os

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import create_engine

from policyengine_api.data.v1_models import V1Base


def compare_existing_schema(database_url: str) -> list:
    """Return metadata drift without mutating the target database."""

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            return compare_metadata(context, V1Base.metadata)
    finally:
        engine.dispose()


@pytest.mark.skipif(
    "STAGE7_EXISTING_DATABASE_URL" not in os.environ,
    reason="A read-only existing Cloud SQL URL was not supplied",
)
def test_live_existing_schema_matches_metadata_without_mutation():
    database_url = os.environ["STAGE7_EXISTING_DATABASE_URL"]
    assert compare_existing_schema(database_url) == []
