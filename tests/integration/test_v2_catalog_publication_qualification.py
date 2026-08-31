"""Production-scale qualification for the installed PolicyEngine.py catalog."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import tracemalloc

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from policyengine_api.data.v2.catalog.extraction import extract_installed_catalog
from policyengine_api.data.v2.catalog.publication import publish_catalog
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL


REPO = Path(__file__).parents[2]
DISPOSABLE_DATABASE = "policyengine_v2_alembic_test"
MAX_ADDITIONAL_PUBLISHER_MEMORY_BYTES = 256 * 1024 * 1024

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_V2_CATALOG_PUBLICATION_QUALIFICATION") != "1",
    reason=(
        "publishes the complete catalog; set RUN_V2_CATALOG_PUBLICATION_QUALIFICATION=1"
    ),
)


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    url = make_url(database_url)
    if url.database != DISPOSABLE_DATABASE or url.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
    }:
        pytest.fail("catalog qualification requires disposable local Postgres")
    return database_url


def test_complete_installed_catalog_bulk_publication() -> None:
    database_url = _disposable_url()
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))

    try:
        catalog = extract_installed_catalog()
        gc.collect()
        tracemalloc.start()
        evidence = publish_catalog(engine, catalog)
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert peak_bytes < MAX_ADDITIONAL_PUBLISHER_MEMORY_BYTES
        assert evidence.entity_counts == catalog.entity_counts()
        with engine.connect() as connection:
            persisted_counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM tax_benefit_models),
                        (SELECT count(*) FROM tax_benefit_model_versions),
                        (SELECT count(*) FROM variables),
                        (SELECT count(*) FROM parameter_nodes),
                        (SELECT count(*) FROM parameters),
                        (SELECT count(*) FROM parameter_values
                          WHERE policy_id IS NULL AND dynamic_id IS NULL),
                        (SELECT count(*) FROM datasets
                          WHERE NOT is_output_dataset AND storage_path IS NULL),
                        (SELECT count(*) FROM regions)
                    """
                )
            ).one()
            representative = connection.execute(
                text(
                    """
                    SELECT
                        EXISTS (SELECT 1 FROM variables
                                WHERE name = 'employment_income'),
                        EXISTS (SELECT 1 FROM parameters
                                WHERE name = 'gov.benefit_uprating_cpi'),
                        EXISTS (SELECT 1 FROM regions WHERE code = 'us'),
                        EXISTS (SELECT 1 FROM regions WHERE code = 'uk')
                    """
                )
            ).one()
        assert tuple(persisted_counts) == (
            evidence.entity_counts["models"],
            evidence.entity_counts["model_versions"],
            evidence.entity_counts["variables"],
            evidence.entity_counts["parameter_nodes"],
            evidence.entity_counts["parameters"],
            evidence.entity_counts["parameter_values"],
            evidence.entity_counts["datasets"],
            evidence.entity_counts["regions"],
        )
        assert all(representative)
        print(
            json.dumps(
                {
                    **evidence.as_dict(),
                    "peak_additional_publisher_memory_bytes": peak_bytes,
                },
                sort_keys=True,
            )
        )
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
        engine.dispose()
