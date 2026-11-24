"""An in-memory v2 catalog database holding the US and UK test catalogs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.fixtures.v2_catalog import normalized_catalog
from tests.fixtures.v2_metadata_service_helpers import insert_country

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmodel import Session


@pytest.fixture
def catalog_session() -> Iterator[Session]:
    with sqlite_v2_sessions() as sessions:
        with sessions.begin() as session:
            for country in normalized_catalog().countries:
                insert_country(session, country, include_model=True)

        with sessions() as session:
            yield session
