"""Record SPM availability on published catalog versions in disposable Postgres.

Catalog publication records it as ``policyengine_v2_catalog_writer``, whose
declared privileges must cover the update (rule
``api.v2.runtime-privileges-tested-as-runtime-role``).
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from policyengine_api.constants import REPO
from policyengine_api.data.v2.catalog.publication_tables import (
    MODEL_VERSIONS,
    MODELS,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
    SPMAvailabilityRecording,
)
from policyengine_api.data.v2.catalog.spm_availability import (
    record_published_spm_availability,
    record_spm_availability,
)
from policyengine_api.data.v2.privileges import CATALOG_WRITER_ROLE

AVAILABLE = {"available": True, "settings_schema": {}, "defaults": {"scenario": "x"}}
UNAVAILABLE = {"available": False}


def test_availability_fills_only_the_named_version_and_only_once(
    disposable_v2_database_url: str, managed_v2_roles, v2_engine_as_role
) -> None:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    writer_engine = v2_engine_as_role(CATALOG_WRITER_ROLE, poolclass=NullPool)
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
        with writer_engine.begin() as connection:
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
        writer_engine.dispose()
        engine.dispose()

    assert first
    assert not again
    assert stored == {version_id: AVAILABLE, other_version_id: None}


def _unreadable_versions(_url: str) -> object:
    msg = "the simulation service's versions could not be read"
    raise CatalogPublicationError(msg)


def test_publication_lists_only_versions_still_unrecorded(
    disposable_v2_database_url: str, managed_v2_roles, v2_engine_as_role
) -> None:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    writer_engine = v2_engine_as_role(CATALOG_WRITER_ROLE, poolclass=NullPool)
    model_ids = {"us": uuid4(), "uk": uuid4()}
    model_names = {
        country_id: f"policyengine-{country_id}-{model_id.hex[:8]}"
        for country_id, model_id in model_ids.items()
    }
    catalog = SimpleNamespace(
        policyengine_version="6.10.0",
        countries=[
            SimpleNamespace(
                country_id=country_id,
                model=SimpleNamespace(name=model_names[country_id]),
                model_version=SimpleNamespace(version="1.450.0"),
            )
            for country_id in ("uk", "us")
        ],
    )
    try:
        with engine.begin() as connection:
            for country_id, model_id in model_ids.items():
                connection.execute(
                    sa.insert(MODELS).values(id=model_id, name=model_names[country_id])
                )
                # An earlier publication recorded the US version. The UK one
                # leaves the column out, as publication's insert does, so it
                # holds SQL NULL rather than JSON null.
                recorded_earlier = (
                    {"spm_availability": AVAILABLE} if country_id == "us" else {}
                )
                connection.execute(
                    sa.insert(MODEL_VERSIONS).values(
                        id=uuid4(),
                        model_id=model_id,
                        version="1.450.0",
                        current_law_id=2,
                        metadata_time_periods=[2026],
                        **recorded_earlier,
                    )
                )
        unreadable = record_published_spm_availability(
            writer_engine,
            catalog,
            {"SIMULATION_ENTRYPOINT_URL": "https://simulation.example"},
            fetch_versions=_unreadable_versions,
        )
        # The simulation service serves no PolicyEngine.py version yet.
        not_served = record_published_spm_availability(
            writer_engine,
            catalog,
            {"SIMULATION_ENTRYPOINT_URL": "https://simulation.example"},
            fetch_versions=lambda _url: {"policyengine": {}},
        )
    finally:
        with engine.begin() as connection:
            for model_id in model_ids.values():
                connection.execute(
                    sa.delete(MODEL_VERSIONS).where(
                        MODEL_VERSIONS.c.model_id == model_id
                    )
                )
                connection.execute(sa.delete(MODELS).where(MODELS.c.id == model_id))
        writer_engine.dispose()
        engine.dispose()

    assert unreadable == SPMAvailabilityRecording(
        not_recorded=(("uk", "1.450.0"),),
        versions_unreadable="the simulation service's versions could not be read",
    )
    # The UK version is recorded unavailable; the US one keeps its value.
    assert not_served == SPMAvailabilityRecording(recorded=(("uk", "1.450.0", False),))
