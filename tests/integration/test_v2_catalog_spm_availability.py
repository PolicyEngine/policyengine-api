"""Record SPM availability on published catalog versions in disposable Postgres."""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from policyengine_api.constants import REPO
from policyengine_api.data.v2.catalog.spm_availability import (
    MODEL_VERSIONS,
    MODELS,
    record_spm_availability,
)

AVAILABLE = {"available": True, "settings_schema": {}, "defaults": {"scenario": "x"}}
UNAVAILABLE = {"available": False}


def test_availability_fills_only_the_named_version_and_only_once(
    disposable_v2_database_url: str,
) -> None:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    model_id, version_id, other_version_id = uuid4(), uuid4(), uuid4()
    model_name = f"policyengine-us-{model_id.hex[:8]}"
    try:
        with engine.begin() as connection:
            connection.execute(sa.insert(MODELS).values(id=model_id, name=model_name))
            connection.execute(
                sa.insert(MODEL_VERSIONS),
                [
                    {
                        "id": identifier,
                        "model_id": model_id,
                        "version": version,
                        "current_law_id": 2,
                        "metadata_time_periods": [2026],
                    }
                    for identifier, version in (
                        (version_id, "1.450.0"),
                        (other_version_id, "1.449.0"),
                    )
                ],
            )
            first = record_spm_availability(
                connection,
                model_name=model_name,
                version="1.450.0",
                availability=AVAILABLE,
            )
            again = record_spm_availability(
                connection,
                model_name=model_name,
                version="1.450.0",
                availability=UNAVAILABLE,
            )
        with engine.connect() as connection:
            stored = dict(
                connection.execute(
                    sa.select(
                        MODEL_VERSIONS.c.id, MODEL_VERSIONS.c.spm_availability
                    ).where(MODEL_VERSIONS.c.model_id == model_id)
                ).all()
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                sa.delete(MODEL_VERSIONS).where(MODEL_VERSIONS.c.model_id == model_id)
            )
            connection.execute(sa.delete(MODELS).where(MODELS.c.id == model_id))
        engine.dispose()

    assert first
    assert not again
    assert stored == {version_id: AVAILABLE, other_version_id: None}
