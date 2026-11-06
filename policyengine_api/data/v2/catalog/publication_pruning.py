"""Prune older stored catalog versions, and restore a pruned version.

Each stored catalog version costs about 550 MB, mostly its current-law
parameter values and its parameter tree rows. Every publication records when
it published each version it publishes (``catalog_last_published_at``). After
a publication commits, catalog publication keeps, for each model of the
catalog it published, the installed version and the
``KEPT_OTHER_CATALOG_VERSIONS`` most recently published other versions, and
prunes every other stored version of that model that is not pruned already,
at most ``MAX_CATALOG_VERSIONS_PRUNED_PER_RUN`` per publication, oldest first.
Keeping two others keeps the version the serving revision runs after a
release whose promotion failed, or a rollback to an older version, since the
release workflow seeds before it deploys. Pruning a version deletes exactly:

- its current-law parameter values: those of its parameters with neither a
  policy nor a dynamic;
- its parameter tree rows;
- its parameter search files;

and sets its ``catalog_values_pruned_at``, all in one transaction. It never
deletes parameters (their values cascade with them, saved reforms' included),
the model version row, its parameter nodes, variables, regions or datasets, or
any value a policy or dynamic owns.

These rows are package-derived: publishing a pruned version again, as a
rollback that installs it does, restores them from the installed packages
inside the publication's transaction. The values are inserted from the staged
catalog here, before the stored version is compared with it, and the tree and
search file are written by the usual writers for a version that has none.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.catalog.publication_inserts import (
    INSERT_PARAMETER_VALUES,
)
from policyengine_api.data.v2.catalog.publication_tables import (
    MODEL_VERSIONS,
    MODELS,
    PARAMETER_VALUES,
    PARAMETERS,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPruningFailure,
)
from policyengine_api.data.v2.models import V2_METADATA

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import Connection

    from policyengine_api.data.v2.catalog.records import CountryCatalog

PARAMETER_TREE_CHILDREN = V2_METADATA.tables["parameter_tree_children"]
PARAMETER_SEARCH_FILES = V2_METADATA.tables["parameter_search_files"]

KEPT_OTHER_CATALOG_VERSIONS = 2
"""How many most recently published versions, besides the installed one, are kept.

The release workflow publishes a release's version before it deploys and
promotes the release, and puts the previous revision back when promotion
fails. After one failed promotion, or a rollback to an older version, the
version still serving is then the second most recently published other one.
"""

MAX_CATALOG_VERSIONS_PRUNED_PER_RUN = 2
"""The most stored catalog versions one publication prunes.

Pruning one PolicyEngine.py version deletes about 1.2 million current-law
value rows across both countries' stored versions, after a publication that
may itself have taken most of the seed job's time limit. Two stored versions
are one release's US and UK versions; the next publications prune the rest.
"""


@dataclass(frozen=True, slots=True)
class StoredCatalogVersion:
    """One stored catalog version of a model, as pruning chooses among them.

    ``last_published_at`` is None for a version no publication has published
    since ``catalog_last_published_at`` was added.
    """

    id: UUID
    model_name: str
    version: str
    created_at: datetime
    values_pruned: bool
    last_published_at: datetime | None = None

    @property
    def publication_order(self) -> tuple[datetime, datetime, str]:
        """Sort key from the least to the most recently published version.

        A version without a publication time stands in its creation time; ties
        are ordered by creation time, then version text.
        """
        published = (
            self.created_at
            if self.last_published_at is None
            else self.last_published_at
        )
        return (published, self.created_at, self.version)


@dataclass(frozen=True, slots=True)
class PrunedRows:
    """The rows pruning deleted from one catalog version, per table."""

    parameter_values: int
    parameter_tree_children: int
    parameter_search_files: int


def catalog_versions_to_prune(
    stored_versions: Iterable[StoredCatalogVersion],
    installed_versions: Mapping[str, str],
) -> tuple[StoredCatalogVersion, ...]:
    """Return the stored versions pruning removes current-law data from.

    ``installed_versions`` maps each model of the published catalog, one per
    country, to the version the publication published or republished. For
    each of those models the installed version and the
    ``KEPT_OTHER_CATALOG_VERSIONS`` most recently published other versions are
    kept (``StoredCatalogVersion.publication_order``), whether or not they
    were pruned before; every other version of the model not pruned already is
    returned. Versions of a model the catalog doesn't name are never returned.
    The result is in model name order, least recently published first within
    a model. This is the one place the rule is decided: publication applies
    it to choose, and again under the publication lock before pruning each
    version.
    """
    versions_by_model: dict[str, list[StoredCatalogVersion]] = defaultdict(list)
    for stored in stored_versions:
        if stored.model_name in installed_versions:
            versions_by_model[stored.model_name].append(stored)
    chosen: list[StoredCatalogVersion] = []
    for model_name in sorted(versions_by_model):
        others = sorted(
            (
                stored
                for stored in versions_by_model[model_name]
                if stored.version != installed_versions[model_name]
            ),
            key=lambda stored: stored.publication_order,
        )
        # The last KEPT_OTHER_CATALOG_VERSIONS are the most recently published.
        chosen.extend(
            stored
            for stored in others[:-KEPT_OTHER_CATALOG_VERSIONS]
            if not stored.values_pruned
        )
    return tuple(chosen)


def catalog_versions_to_prune_now(
    chosen: Iterable[StoredCatalogVersion],
    limit: int = MAX_CATALOG_VERSIONS_PRUNED_PER_RUN,
) -> tuple[tuple[StoredCatalogVersion, ...], int]:
    """Return the chosen versions this run prunes, and how many are left.

    A run prunes at most ``limit`` versions, the oldest created first; versions
    created at the same instant, as one publication creates every country's,
    are ordered by model name and then version. The next publications prune
    the ones left.
    """
    ordered = sorted(
        chosen,
        key=lambda stored: (stored.created_at, stored.model_name, stored.version),
    )
    return tuple(ordered[:limit]), max(len(ordered) - limit, 0)


def read_stored_catalog_versions(
    connection: Connection, model_names: Iterable[str]
) -> tuple[StoredCatalogVersion, ...]:
    """Return every stored version of the named models."""
    rows = connection.execute(
        sa.select(
            MODEL_VERSIONS.c.id,
            MODELS.c.name,
            MODEL_VERSIONS.c.version,
            MODEL_VERSIONS.c.created_at,
            MODEL_VERSIONS.c.catalog_values_pruned_at,
            MODEL_VERSIONS.c.catalog_last_published_at,
        )
        .select_from(
            MODEL_VERSIONS.join(MODELS, MODELS.c.id == MODEL_VERSIONS.c.model_id)
        )
        .where(MODELS.c.name.in_(list(model_names)))
    )
    return tuple(
        StoredCatalogVersion(
            id=row.id,
            model_name=row.name,
            version=row.version,
            created_at=row.created_at,
            values_pruned=row.catalog_values_pruned_at is not None,
            last_published_at=row.catalog_last_published_at,
        )
        for row in rows
    )


def record_catalog_publication(
    connection: Connection, countries: Sequence[CountryCatalog]
) -> None:
    """Record that this publication published each catalog country's version.

    Sets ``catalog_last_published_at`` to the publication transaction's start
    time for the stored version of each country, whether the publication
    inserted it, found it unchanged or restored it. Runs inside publication's
    transaction, after the versions are stored.
    """
    for country in countries:
        connection.execute(
            sa.update(MODEL_VERSIONS)
            .where(
                MODEL_VERSIONS.c.version == country.model_version.version,
                MODEL_VERSIONS.c.model_id.in_(
                    sa.select(MODELS.c.id).where(MODELS.c.name == country.model.name)
                ),
            )
            .values(catalog_last_published_at=sa.func.current_timestamp())
        )


def prune_catalog_version(
    connection: Connection, version_id: UUID
) -> PrunedRows | None:
    """Delete one version's current-law values, tree rows and search files.

    Sets the version's ``catalog_values_pruned_at`` first, only if it is
    unset, and returns None without deleting anything when it was set already.
    Runs in the caller's transaction, which holds the publication lock, so the
    deletes and the marker commit or roll back together.
    """
    marked = connection.execute(
        sa.update(MODEL_VERSIONS)
        .where(
            MODEL_VERSIONS.c.id == version_id,
            MODEL_VERSIONS.c.catalog_values_pruned_at.is_(None),
        )
        .values(catalog_values_pruned_at=sa.func.current_timestamp())
    )
    # A guard publication can't reach: every writer of the column (pruning
    # and restoration) holds the publication lock, and the caller checks under
    # it that the version is unpruned. It costs nothing in the UPDATE, and
    # keeps a writer that doesn't take the lock, such as an operator's SQL,
    # from having a version's time replaced or its rows deleted twice.
    if marked.rowcount == 0:
        return None
    version_parameter_ids = sa.select(PARAMETERS.c.id).where(
        PARAMETERS.c.tax_benefit_model_version_id == version_id
    )
    parameter_values = connection.execute(
        sa.delete(PARAMETER_VALUES).where(
            PARAMETER_VALUES.c.parameter_id.in_(version_parameter_ids),
            PARAMETER_VALUES.c.policy_id.is_(None),
            PARAMETER_VALUES.c.dynamic_id.is_(None),
        )
    ).rowcount
    tree_rows = connection.execute(
        sa.delete(PARAMETER_TREE_CHILDREN).where(
            PARAMETER_TREE_CHILDREN.c.tax_benefit_model_version_id == version_id
        )
    ).rowcount
    search_files = connection.execute(
        sa.delete(PARAMETER_SEARCH_FILES).where(
            PARAMETER_SEARCH_FILES.c.tax_benefit_model_version_id == version_id
        )
    ).rowcount
    return PrunedRows(
        parameter_values=parameter_values,
        parameter_tree_children=tree_rows,
        parameter_search_files=search_files,
    )


def pruning_failure(
    country_id: str, version: str | None, error: Exception
) -> CatalogPruningFailure:
    """Describe a failed pruning without its statement, parameters or row data.

    ``version`` is None when reading the stored versions failed, before any
    version was chosen. SQLAlchemy's message quotes the statement and its
    parameters, and the database's own message may quote values, so only the
    class name and SQLSTATE of the error the database driver raised are
    reported. Of any other exception only the class name is, since its
    message may hold row data too.
    """
    if isinstance(error, SQLAlchemyError):
        driver_error = getattr(error, "orig", None)
        reported = type(error if driver_error is None else driver_error).__name__
        sqlstate = getattr(driver_error, "sqlstate", None)
        if isinstance(sqlstate, str) and sqlstate:
            reported = f"{reported} (SQLSTATE {sqlstate})"
        cause = f"the database reported {reported}"
    else:
        cause = f"it raised {type(error).__name__}"
    failed = (
        f"reading the stored {country_id} catalog versions to choose which to "
        "prune failed"
        if version is None
        else (
            f"pruning the {country_id} catalog version {version} failed and was "
            "rolled back"
        )
    )
    return CatalogPruningFailure(
        country_id=country_id,
        policyengine_version=version,
        error_type=type(error).__name__,
        message=f"{failed}: {cause}",
    )


def _pruned_version_id(connection: Connection, country: CountryCatalog) -> UUID | None:
    pruned_id: UUID | None = connection.execute(
        sa.select(MODEL_VERSIONS.c.id)
        .select_from(
            MODEL_VERSIONS.join(MODELS, MODELS.c.id == MODEL_VERSIONS.c.model_id)
        )
        .where(
            MODELS.c.name == country.model.name,
            MODEL_VERSIONS.c.version == country.model_version.version,
            MODEL_VERSIONS.c.catalog_values_pruned_at.is_not(None),
        )
    ).scalar_one_or_none()
    return pruned_id


def restore_pruned_catalog_versions(
    connection: Connection, countries: Sequence[CountryCatalog]
) -> tuple[tuple[str, str, int], ...]:
    """Write back the current-law values of each staged version that was pruned.

    Inserts the staged catalog's values, with their catalog IDs, for the
    stored parameters of the same names, as publishing a new version does, and
    clears the version's marker. Returns the country, version and values
    written for each, in catalog order. Runs inside publication's transaction,
    after staging and before the stored versions are compared with the staged
    catalog, which then checks the restored values like every other table.
    """
    restored = []
    for country in countries:
        version_id = _pruned_version_id(connection, country)
        if version_id is None:
            continue
        # SQLAlchemy keeps an INSERT's row count only when asked to.
        parameter_values = connection.execute(
            INSERT_PARAMETER_VALUES.execution_options(preserve_rowcount=True),
            {"country_id": country.country_id},
        ).rowcount
        connection.execute(
            sa.update(MODEL_VERSIONS)
            .where(MODEL_VERSIONS.c.id == version_id)
            .values(catalog_values_pruned_at=None)
        )
        restored.append(
            (country.country_id, country.model_version.version, parameter_values)
        )
    return tuple(restored)
