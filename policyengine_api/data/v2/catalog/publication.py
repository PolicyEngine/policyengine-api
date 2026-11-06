"""Atomic PostgreSQL publication for a validated PolicyEngine.py catalog."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.catalog.publication_inserts import publish_new_country
from policyengine_api.data.v2.catalog.publication_parameter_search_file import (
    assert_parameter_search_files_written,
    write_parameter_search_files,
)
from policyengine_api.data.v2.catalog.publication_parameter_tree import (
    assert_parameter_trees_written,
    write_parameter_trees,
)
from policyengine_api.data.v2.catalog.publication_pruning import (
    catalog_versions_to_prune,
    prune_catalog_version,
    pruning_failure,
    read_stored_catalog_versions,
    restore_pruned_catalog_versions,
)
from policyengine_api.data.v2.catalog.publication_reconciliation import (
    assert_canonical_value_uniqueness,
    assert_country_matches,
    count_region_differences,
    count_stored_regions,
    update_stored_time_periods,
    version_exists,
)
from policyengine_api.data.v2.catalog.publication_staging import (
    create_staging_tables,
    stage_catalog,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPruningFailure,
    CatalogPublicationError,
    PrunedCatalogVersion,
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
    """Publish one complete catalog atomically and return non-secret evidence.

    A catalog version that is already stored is compared with the staged one
    and left as it is, apart from two exceptions: it keeps the regions it was
    published with, and it takes the staged time periods
    (``metadata_time_periods``), the years the Public API offers for it.
    In the same transaction it writes the parameter tree and the parameter
    search file of each version in the catalog that has none, built from the
    catalog: the versions it publishes, and the installed version when an
    earlier release stored it with catalog format 2 but without them. Other
    stored versions, and an installed version stored before catalog format 2,
    keep having none. A stored version that pruning removed current-law data
    from gets its values back from the staged catalog, before the comparison,
    and its tree and search file from those writers.

    After the transaction commits, it prunes the older stored versions of the
    catalog's models (``publication_pruning``), one transaction each; a
    failure rolls back only that version and is reported in the evidence.
    """
    started = time.monotonic()
    with engine.begin() as connection:
        _verify_expected_revision(connection)
        _acquire_publication_lock(connection)
        before = _protected_row_counts(connection)
        create_staging_tables(connection)
        stage_catalog(connection, catalog, checkpoint=checkpoint)
        if checkpoint is not None:
            checkpoint("after_copy", connection)

        restored_versions = restore_pruned_catalog_versions(
            connection, catalog.countries
        )
        stored_versions = _reconcile_stored_versions(connection, catalog)
        existing = stored_versions.countries

        for country in catalog.countries:
            if country.country_id not in existing:
                publish_new_country(connection, country)
        parameter_trees_written = write_parameter_trees(connection, catalog.countries)
        parameter_search_files_written = write_parameter_search_files(
            connection, catalog.countries
        )
        if checkpoint is not None:
            checkpoint("after_reconciliation", connection)

        for country in catalog.countries:
            assert_country_matches(
                connection,
                country,
                include_regions=country.country_id not in existing,
            )
        assert_canonical_value_uniqueness(connection)
        assert_parameter_trees_written(connection, catalog.countries)
        assert_parameter_search_files_written(connection, catalog.countries)
        if _protected_row_counts(connection) != before:
            msg = "publication changed simulation, report, or dataset-version rows"
            raise CatalogPublicationError(msg)
        if checkpoint is not None:
            checkpoint("after_validation", connection)

    pruned_versions, pruning_failures = _prune_older_versions(engine, catalog)
    return replace(
        _evidence(
            catalog,
            stored_versions,
            parameter_trees_written=parameter_trees_written,
            parameter_search_files_written=parameter_search_files_written,
            started=started,
        ),
        restored_catalog_versions=restored_versions,
        pruned_catalog_versions=pruned_versions,
        catalog_pruning_failures=pruning_failures,
    )


def _prune_older_versions(
    engine: Engine, catalog: NormalizedCatalog
) -> tuple[tuple[PrunedCatalogVersion, ...], tuple[CatalogPruningFailure, ...]]:
    """Prune the catalog models' older versions, one transaction each.

    Returns the versions pruned and those whose pruning failed. Runs after the
    publication committed. Each version's transaction takes the
    publication lock, so it waits for any other publisher, and deletes and
    marks the version together (``prune_catalog_version``). A database error
    rolls back that version alone and is recorded, and the others are still
    pruned; the next publication retries it. A database error reading the
    stored versions prunes nothing and is recorded for each model, with no
    version.
    """
    installed_versions = {
        country.model.name: country.model_version.version
        for country in catalog.countries
    }
    country_ids = {
        country.model.name: country.country_id for country in catalog.countries
    }
    try:
        with engine.connect() as connection:
            stored_versions = read_stored_catalog_versions(
                connection, installed_versions
            )
    except SQLAlchemyError as error:
        return (), tuple(
            pruning_failure(country_ids[model_name], None, error)
            for model_name in sorted(country_ids)
        )
    pruned: list[PrunedCatalogVersion] = []
    failures: list[CatalogPruningFailure] = []
    for stored in catalog_versions_to_prune(stored_versions, installed_versions):
        country_id = country_ids[stored.model_name]
        try:
            with engine.begin() as connection:
                _acquire_publication_lock(connection)
                deleted = prune_catalog_version(connection, stored.id)
        except SQLAlchemyError as error:
            failures.append(pruning_failure(country_id, stored.version, error))
            continue
        if deleted is not None:
            pruned.append(
                PrunedCatalogVersion(
                    country_id=country_id,
                    policyengine_version=stored.version,
                    parameter_values=deleted.parameter_values,
                    parameter_tree_children=deleted.parameter_tree_children,
                    parameter_search_files=deleted.parameter_search_files,
                )
            )
    return tuple(pruned), tuple(failures)


@dataclass(frozen=True, slots=True)
class _StoredVersions:
    """The catalog's countries whose version was already stored, and what changed.

    ``kept_region_summaries`` and ``time_period_updates`` take the shapes of
    the evidence fields of the same names.
    """

    countries: frozenset[str]
    kept_region_summaries: tuple[tuple[str, str, int, int], ...]
    time_period_updates: tuple[tuple[str, str, tuple[int, ...], tuple[int, ...]], ...]


def _reconcile_stored_versions(
    connection: Connection,
    catalog: NormalizedCatalog,
) -> _StoredVersions:
    """Compare each stored catalog version, then give it the staged time periods.

    A stored version's regions stay as they were published even when the
    reference files differ now. Its time periods (``metadata_time_periods``)
    become the staged ones, which come from the Public API's code. Every other
    table and column must still match exactly, or CatalogPublicationError is
    raised before anything is changed.
    """
    countries: set[str] = set()
    kept_region_summaries: list[tuple[str, str, int, int]] = []
    time_period_updates: list[tuple[str, str, tuple[int, ...], tuple[int, ...]]] = []
    for country in catalog.countries:
        if version_exists(connection, country):
            assert_country_matches(connection, country, include_regions=False)
            kept = _kept_region_summary(connection, country)
            if kept is not None:
                kept_region_summaries.append(kept)
            countries.add(country.country_id)
    for country in catalog.countries:
        if country.country_id in countries:
            update = _time_period_update(connection, country)
            if update is not None:
                time_period_updates.append(update)
    return _StoredVersions(
        countries=frozenset(countries),
        kept_region_summaries=tuple(kept_region_summaries),
        time_period_updates=tuple(time_period_updates),
    )


def _time_period_update(
    connection: Connection,
    country: CountryCatalog,
) -> tuple[str, str, tuple[int, ...], tuple[int, ...]] | None:
    """Give a stored version the staged time periods, and log any change.

    Return the country, the version, and the stored and staged time periods
    when they differed; there is none when they are the same.
    """
    update = update_stored_time_periods(connection, country)
    if update is None:
        return None
    stored, staged = update
    # The seed command configures no logging handler, so the details are in the
    # message itself; the attributes serve structured handlers.
    LOGGER.warning(
        "replaced the time periods of the stored %s catalog version %s: %s became %s",
        country.country_id,
        country.model_version.version,
        stored,
        staged,
        extra={
            "policyengine_attributes": {
                "country_id": country.country_id,
                "policyengine_version": country.model_version.version,
                "stored_time_periods": stored,
                "staged_time_periods": staged,
            }
        },
    )
    return (
        country.country_id,
        country.model_version.version,
        tuple(stored),
        tuple(staged),
    )


def _evidence(
    catalog: NormalizedCatalog,
    stored_versions: _StoredVersions,
    *,
    parameter_trees_written: tuple[tuple[str, str, int], ...],
    parameter_search_files_written: tuple[tuple[str, str, int, int], ...],
    started: float,
) -> PublicationEvidence:
    """Describe what is stored after publication.

    Every table of a stored version matches the staged catalog except regions
    that were kept: for those countries the evidence counts the stored region
    rows and reports none of the staged fallbacks or omissions, which describe
    rows that were not published. It lists each stored version whose time
    periods publication replaced, with the previous and new ones, and the
    parameter trees and search files publication wrote. The caller adds the
    pruned versions publication restored and the older versions it pruned.
    """
    kept_region_summaries = stored_versions.kept_region_summaries
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
        time_period_updates=stored_versions.time_period_updates,
        parameter_trees_written=parameter_trees_written,
        parameter_search_files_written=parameter_search_files_written,
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
