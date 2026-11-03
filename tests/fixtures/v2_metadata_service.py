"""An in-memory v2 catalog database holding the US and UK test catalogs."""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import V2_METADATA
from tests.fixtures.v2_catalog import normalized_catalog
from tests.fixtures.v2_metadata_service_helpers import insert_country


@pytest.fixture
def catalog_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(engine)
    with Session(engine) as session:
        for country in normalized_catalog().countries:
            insert_country(session, country, include_model=True)
        session.commit()

    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
