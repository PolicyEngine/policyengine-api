"""Compare ORM metadata with an existing v1 schema without mutating it."""

import os

import pytest
from sqlalchemy import create_engine

from scripts.v1_database_migration import metadata_differences


def compare_existing_schema(database_url: str) -> list[str]:
    """Return metadata drift without mutating the target database."""

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return sorted(metadata_differences(connection))
    finally:
        engine.dispose()


@pytest.mark.skipif(
    "STAGE7_EXISTING_DATABASE_URL" not in os.environ,
    reason="A read-only existing Cloud SQL URL was not supplied",
)
def test_live_existing_schema_matches_metadata_without_mutation():
    database_url = os.environ["STAGE7_EXISTING_DATABASE_URL"]
    assert compare_existing_schema(database_url) == []
