"""An in-memory v2 catalog database holding the US and UK test catalogs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.fixtures.v2_catalog import normalized_catalog
from tests.fixtures.v2_metadata_service_helpers import insert_country

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


@pytest.fixture
def catalog_sessions() -> Iterator[sessionmaker[Session]]:
    """Return Session factories of a database holding the US and UK catalogs."""
    with sqlite_v2_sessions() as sessions:
        with sessions.begin() as session:
            for country in normalized_catalog().countries:
                insert_country(session, country, include_model=True)
        yield sessions


@pytest.fixture
def catalog_session(catalog_sessions: sessionmaker[Session]) -> Iterator[Session]:
    """Return a Session of the catalog database, closed after the test.

    A commit expires its rows, as a plain SQLModel ``Session`` does, so a read
    after a commit sees the stored values, not the ones the Session held.
    """
    with catalog_sessions(expire_on_commit=True) as session:
        yield session
