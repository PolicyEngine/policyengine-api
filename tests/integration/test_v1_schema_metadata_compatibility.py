"""Compare ORM metadata with an existing v1 schema without mutating it."""

import os

import pytest

from policyengine_api.data.v1_sessions import unpooled_v1_sessions
from scripts.v1_database_migration import metadata_differences


def compare_existing_schema(database_url: str) -> list[str]:
    """Return metadata drift without mutating the target database."""
    with unpooled_v1_sessions(database_url) as sessions, sessions() as session:
        return sorted(metadata_differences(session))


@pytest.mark.skipif(
    "STAGE7_EXISTING_DATABASE_URL" not in os.environ,
    reason="A read-only existing Cloud SQL URL was not supplied",
)
def test_live_existing_schema_matches_metadata_without_mutation() -> None:
    database_url = os.environ["STAGE7_EXISTING_DATABASE_URL"]
    assert compare_existing_schema(database_url) == []
