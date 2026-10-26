"""Atomic PostgreSQL publication for a validated PolicyEngine.py catalog."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import Connection, Engine

from policyengine_api.data.v2.catalog.publication_reconciliation import (
    assert_canonical_value_uniqueness,
    assert_country_matches,
    count_region_differences,
    count_stored_regions,
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
from policyengine_api.data.v2.migration_target import V2_ALEMBIC_HEAD_REVISION
from policyengine_api.data.v2.models import (
    DatasetVersion,
    Report,
    ReportRun,
    Simulation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.data.v2.catalog.records import (
        CountryCatalog,
        NormalizedCatalog,
    )

# Stable application-defined PostgreSQL lock ID shared by all v2 catalog publishers.
PUBLICATION_ADVISORY_LOCK_KEY = 8_629_020_026_090_001

ALEMBIC_VERSION = sa.table(
    "alembic_version",
    sa.column("version_num", sa.String),
)
PROTECTED_TABLES = (
    DatasetVersion.__table__,
    Simulation.__table__,
    Report.__table__,
    ReportRun.__table__,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "CatalogPublicationError",
    "PublicationEvidence",
    "publish_catalog",
    "unpublished_countries",
]


def _verify_expected_revision(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        msg = "catalog publication requires PostgreSQL"
        raise CatalogPublicationError(msg)
    if not sa.inspect(connection).has_table(ALEMBIC_VERSION.name):
        msg = "the v2 Alembic revision table is absent"
        raise CatalogPublicationError(msg)
    revisions = set(
        connection.execute(sa.select(ALEMBIC_VERSION.c.version_num)).scalars()
    )
    if revisions != {V2_ALEMBIC_HEAD_REVISION}:
        msg = "the v2 database is not at the expected Alembic revision"
        raise CatalogPublicationError(msg)


def _acquire_publication_lock(connection: Connection) -> None:
    connection.execute(
        sa.select(sa.func.pg_advisory_xact_lock(PUBLICATION_ADVISORY_LOCK_KEY))
    ).scalar_one()


def _protected_row_counts(connection: Connection) -> tuple[int, int, int, int]:
    return tuple(
        connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
        for table in PROTECTED_TABLES
    )


def unpublished_countries(
    engine: Engine, catalog: NormalizedCatalog
) -> tuple[str, ...]:
    """Return the countries whose catalog version is not stored yet, in catalog order.

    It first requires the expected v2 revision, as publication does, so a
    missing or older schema is reported as such. A read outside publication's
    transaction: a version another publisher adds meanwhile is still compared
    with the staged one when this one publishes.
    """
    with engine.connect() as connection:
        _verify_expected_revision(connection)
        return tuple(
            country.country_id
            for country in catalog.countries
            if not version_exists(connection, country)
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

        existing, kept_region_summaries = _check_stored_versions(connection, catalog)

        for country in catalog.countries:
            if country.country_id not in existing:
                publish_new_country(connection, country)
        if checkpoint is not None:
            checkpoint("after_reconciliation", connection)

        for country in catalog.countries:
            assert_country_matches(
                connection,
                country,
                include_regions=country.country_id not in existing,
            )
        assert_canonical_value_uniqueness(connection)
        if _protected_row_counts(connection) != before:
            msg = "publication changed simulation, report, or dataset-version rows"
            raise CatalogPublicationError(msg)
        if checkpoint is not None:
            checkpoint("after_validation", connection)

    return _evidence(catalog, kept_region_summaries, started=started)


def _check_stored_versions(
    connection: Connection,
    catalog: NormalizedCatalog,
) -> tuple[set[str], tuple[tuple[str, str, int, int], ...]]:
    """Compare each stored catalog version and return its countries and kept regions.

    A stored catalog version never changes. Its regions stay as they were
    published even when the reference files differ now; every other table
    must still match exactly.
    """
    existing: set[str] = set()
    kept_region_summaries: list[tuple[str, str, int, int]] = []
    for country in catalog.countries:
        if version_exists(connection, country):
            assert_country_matches(connection, country, include_regions=False)
            kept = _kept_region_summary(connection, country)
            if kept is not None:
                kept_region_summaries.append(kept)
            existing.add(country.country_id)
    return existing, tuple(kept_region_summaries)


def _evidence(
    catalog: NormalizedCatalog,
    kept_region_summaries: tuple[tuple[str, str, int, int], ...],
    *,
    started: float,
) -> PublicationEvidence:
    """Describe what is stored after publication.

    Every table of a stored version matches the staged catalog except regions
    that were kept: for those countries the evidence counts the stored region
    rows and reports none of the staged fallbacks or omissions, which describe
    rows that were not published.
    """
    kept_countries = {country_id for country_id, *_counts in kept_region_summaries}
    entity_counts = catalog.entity_counts()
    entity_counts["regions"] += sum(
        stored - staged for _country, _version, stored, staged in kept_region_summaries
    )
    fallback_summaries = tuple(
        (country.country_id, summary.region_type, summary.count)
        for country in catalog.countries
        if country.country_id not in kept_countries
        for summary in country.fallback_summaries
    )
    _log_fallback_warning(fallback_summaries)
    return PublicationEvidence(
        policyengine_version=catalog.policyengine_version,
        dependency_versions=catalog.dependency_versions,
        entity_counts=entity_counts,
        fallback_summaries=fallback_summaries,
        elapsed_seconds=time.monotonic() - started,
        omitted_region_summaries=tuple(
            (country.country_id, summary.region_type, summary.count)
            for country in catalog.countries
            if country.country_id not in kept_countries
            for summary in country.omitted_region_summaries
        ),
        kept_region_summaries=kept_region_summaries,
    )


def _kept_region_summary(
    connection: Connection,
    country: CountryCatalog,
) -> tuple[str, str, int, int] | None:
    """Return and log how a stored version's kept regions differ from the staged.

    The summary is the country, the version and the stored and staged region
    counts; there is none when the regions are the same. The log names counts
    only.
    """
    staged_not_stored, stored_not_staged = count_region_differences(connection, country)
    if not staged_not_stored and not stored_not_staged:
        return None
    # The seed command configures no logging handler, so the details are in the
    # message itself; the attributes serve structured handlers.
    LOGGER.warning(
        "kept the published regions of the stored %s catalog version %s: %d staged "
        "region rows are not stored and %d stored region rows are not staged",
        country.country_id,
        country.model_version.version,
        staged_not_stored,
        stored_not_staged,
        extra={
            "policyengine_attributes": {
                "country_id": country.country_id,
                "policyengine_version": country.model_version.version,
                "staged_region_rows_not_stored": staged_not_stored,
                "stored_region_rows_not_staged": stored_not_staged,
            }
        },
    )
    return (
        country.country_id,
        country.model_version.version,
        count_stored_regions(connection, country),
        len(country.regions),
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
