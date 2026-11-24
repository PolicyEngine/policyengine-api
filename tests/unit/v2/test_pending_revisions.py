"""Tests for the check of whether a v2 Alembic revision is still to be applied."""

from __future__ import annotations

from policyengine_api.data.v2.household_migration_qualification import (
    HOUSEHOLD_MIGRATION_REVISION,
)
from policyengine_api.data.v2.pending_revisions import v2_revision_is_pending
from tests.fixtures.database_sessions import sqlite_v2_sessions


def test_every_revision_is_pending_for_a_database_alembic_never_stamped() -> None:
    with sqlite_v2_sessions() as sessions, sessions() as session:
        assert v2_revision_is_pending(session, HOUSEHOLD_MIGRATION_REVISION)


def test_a_revision_outside_the_v2_chain_is_never_pending() -> None:
    with sqlite_v2_sessions() as sessions, sessions() as session:
        assert not v2_revision_is_pending(session, "000000000000")
