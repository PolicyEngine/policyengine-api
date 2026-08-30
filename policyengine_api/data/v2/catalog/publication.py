"""Atomic PostgreSQL publication for a validated PolicyEngine.py catalog."""

from __future__ import annotations

from collections.abc import Callable
import logging
import time

from sqlalchemy import Connection, Engine, text

from policyengine_api.data.v2.catalog.publication_reconciliation import (
    assert_canonical_value_uniqueness,
    assert_country_matches,
    publish_new_country,
    version_exists,
)
from policyengine_api.data.v2.catalog.publication_staging import (
    create_staging_tables,
    stage_catalog,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
    PublicationEvidence,
)
from policyengine_api.data.v2.catalog.records import NormalizedCatalog


EXPECTED_ALEMBIC_REVISION = "68b4a5ae5dc5"
PUBLICATION_ADVISORY_LOCK_KEY = 8_629_020_026_090_001

LOGGER = logging.getLogger(__name__)

__all__ = [
    "CatalogPublicationError",
    "PublicationEvidence",
    "publish_catalog",
]


def _verify_expected_revision(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        raise CatalogPublicationError("catalog publication requires PostgreSQL")
    version_table = connection.execute(
        text("SELECT to_regclass('public.alembic_version')")
    ).scalar_one()
    if version_table is None:
        raise CatalogPublicationError("the v2 Alembic revision table is absent")
    revisions = set(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
    )
    if revisions != {EXPECTED_ALEMBIC_REVISION}:
        raise CatalogPublicationError(
            "the v2 database is not at the expected Alembic revision"
        )


def _acquire_publication_lock(connection: Connection) -> None:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": PUBLICATION_ADVISORY_LOCK_KEY},
    ).scalar_one()


def _protected_row_counts(connection: Connection) -> tuple[int, int, int, int]:
    return tuple(
        connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
        for table_name in (
            "dataset_versions",
            "simulations",
            "reports",
            "report_runs",
        )
    )


def publish_catalog(
    engine: Engine,
    catalog: NormalizedCatalog,
    *,
    checkpoint: Callable[[str, Connection], None] | None = None,
) -> PublicationEvidence:
    """Publish one complete catalog atomically and return non-secret evidence."""

    started = time.monotonic()
    with engine.begin() as connection:
        _verify_expected_revision(connection)
        _acquire_publication_lock(connection)
        before = _protected_row_counts(connection)
        create_staging_tables(connection)
        stage_catalog(connection, catalog, checkpoint=checkpoint)
        if checkpoint is not None:
            checkpoint("after_copy", connection)

        existing: set[str] = set()
        for country in catalog.countries:
            if version_exists(connection, country.country_id):
                assert_country_matches(connection, country.country_id)
                existing.add(country.country_id)

        for country in catalog.countries:
            if country.country_id not in existing:
                publish_new_country(connection, country.country_id)
        if checkpoint is not None:
            checkpoint("after_reconciliation", connection)

        for country in catalog.countries:
            assert_country_matches(connection, country.country_id)
        assert_canonical_value_uniqueness(connection)
        if _protected_row_counts(connection) != before:
            raise CatalogPublicationError(
                "publication changed simulation, report, or dataset-version rows"
            )
        if checkpoint is not None:
            checkpoint("after_validation", connection)

    fallback_summaries = tuple(
        (country.country_id, summary.region_type, summary.count)
        for country in catalog.countries
        for summary in country.fallback_summaries
    )
    _log_fallback_warning(fallback_summaries)
    return PublicationEvidence(
        policyengine_version=catalog.policyengine_version,
        dependency_versions=catalog.dependency_versions,
        entity_counts=catalog.entity_counts(),
        fallback_summaries=fallback_summaries,
        elapsed_seconds=time.monotonic() - started,
    )


def _log_fallback_warning(
    fallback_summaries: tuple[tuple[str, str, int], ...],
) -> None:
    if not fallback_summaries:
        return
    LOGGER.warning(
        "PolicyEngine.py regional dataset fallback summary: %s",
        fallback_summaries,
    )
