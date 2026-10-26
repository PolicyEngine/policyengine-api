"""Write the parameter tree of the installed catalog's versions.

Publication writes the tree of each country version in the catalog it
publishes, which is extracted from the installed packages: versions it
publishes now, and the installed version when an earlier release stored it
without a tree. The rows are built from the catalog's own parameter and node
records (``parameter_tree``), never from rows an earlier release stored. Only
the stored parameters' IDs are read, by name, so tree rows reference the stored
parameters; publication has already checked that those stored rows match the
catalog. Writing only inserts rows for a version that has no tree; no other
table changes.

Other stored versions get no tree here: deriving their rows from what earlier
releases stored would be a data migration, which the migration rules leave to
a human decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa

from policyengine_api.data.v2.catalog.parameter_tree import (
    ParameterTreeChildRow,
    TreeNodeSource,
    TreeParameterSource,
    build_parameter_tree,
)
from policyengine_api.data.v2.catalog.publication_staging import copy_rows
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.models import (
    Parameter,
    ParameterTreeChild,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from uuid import UUID

    from sqlalchemy import Connection

    from policyengine_api.data.v2.catalog.records import CountryCatalog

MODELS = TaxBenefitModel.__table__
MODEL_VERSIONS = TaxBenefitModelVersion.__table__
PARAMETERS = Parameter.__table__
PARAMETER_TREE_CHILDREN = ParameterTreeChild.__table__


def _stored_version_id(connection: Connection, country: CountryCatalog) -> UUID:
    return connection.execute(
        sa.select(MODEL_VERSIONS.c.id)
        .select_from(
            MODEL_VERSIONS.join(MODELS, MODELS.c.id == MODEL_VERSIONS.c.model_id)
        )
        .where(
            MODELS.c.name == country.model.name,
            MODEL_VERSIONS.c.version == country.model_version.version,
        )
    ).scalar_one()


def _has_tree(connection: Connection, version_id: UUID) -> bool:
    return bool(
        connection.execute(
            sa.select(
                sa.exists().where(
                    PARAMETER_TREE_CHILDREN.c.tax_benefit_model_version_id == version_id
                )
            )
        ).scalar_one()
    )


def _stored_parameter_ids(connection: Connection, version_id: UUID) -> dict[str, UUID]:
    return {
        row.name: row.id
        for row in connection.execute(
            sa.select(PARAMETERS.c.name, PARAMETERS.c.id).where(
                PARAMETERS.c.tax_benefit_model_version_id == version_id
            )
        )
    }


def _catalog_tree(
    country: CountryCatalog, stored_parameter_ids: dict[str, UUID]
) -> tuple[ParameterTreeChildRow, ...]:
    missing = [
        parameter.name
        for parameter in country.parameters
        if parameter.name not in stored_parameter_ids
    ]
    if missing:
        msg = (
            f"the stored {country.country_id} catalog version "
            f"{country.model_version.version} lacks the parameter {missing[0]}"
        )
        raise CatalogPublicationError(msg)
    return build_parameter_tree(
        nodes=[
            TreeNodeSource(name=node.name, label=node.label)
            for node in country.parameter_nodes
        ],
        parameters=[
            TreeParameterSource(
                id=stored_parameter_ids[parameter.name],
                name=parameter.name,
                label=parameter.label,
                economy=parameter.economy,
                household=parameter.household,
            )
            for parameter in country.parameters
        ],
    )


def _table_rows(
    version_id: UUID,
    rows: tuple[ParameterTreeChildRow, ...],
) -> Iterator[tuple[object, ...]]:
    created_at = datetime.now(UTC)
    column_names = [column.name for column in PARAMETER_TREE_CHILDREN.columns]
    for row in rows:
        values: dict[str, object] = {
            "id": uuid4(),
            "created_at": created_at,
            "tax_benefit_model_version_id": version_id,
            "parent_path": row.parent_path,
            "path": row.path,
            "position": row.position,
            "label": row.label,
            "child_type": row.child_type,
            "child_count": row.child_count,
            "reform_position": row.reform_position,
            "reform_child_count": row.reform_child_count,
            "parameter_id": row.parameter_id,
            "economy": row.economy,
            "household": row.household,
        }
        yield tuple(values[name] for name in column_names)


def write_parameter_trees(
    connection: Connection,
    countries: Sequence[CountryCatalog],
) -> tuple[tuple[str, str, int], ...]:
    """Write the tree of each catalog country's stored version that has none.

    Returns the model name, version and number of rows written for each
    version, in model name order. Runs inside publication's transaction and
    advisory lock, after the countries' versions are stored and checked.
    """
    written = []
    for country in countries:
        version_id = _stored_version_id(connection, country)
        if _has_tree(connection, version_id):
            continue
        rows = _catalog_tree(country, _stored_parameter_ids(connection, version_id))
        count = copy_rows(
            connection,
            table=PARAMETER_TREE_CHILDREN,
            rows=_table_rows(version_id, rows),
        )
        written.append((country.model.name, country.model_version.version, count))
    return tuple(sorted(written))


def assert_parameter_trees_written(
    connection: Connection,
    countries: Sequence[CountryCatalog],
) -> None:
    """Raise CatalogPublicationError if a catalog country's version has no tree."""
    for country in countries:
        if not _has_tree(connection, _stored_version_id(connection, country)):
            msg = (
                f"the {country.country_id} catalog version "
                f"{country.model_version.version} has no parameter tree"
            )
            raise CatalogPublicationError(msg)
