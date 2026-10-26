"""Write the parameter tree of each catalog version a publication publishes.

A version's tree rows are derived from the parameters and parameter nodes the
publication has just stored for it (``parameter_tree``), in the same
transaction. Writing only inserts rows for those versions; no other table
changes.

Versions stored before the tree existed get none here: deriving their rows
from what earlier releases stored would be a data migration, which the
migration rules leave to a human decision.
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
    ParameterNode,
    ParameterTreeChild,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from uuid import UUID

    from sqlalchemy import Connection

MODELS = TaxBenefitModel.__table__
MODEL_VERSIONS = TaxBenefitModelVersion.__table__
PARAMETERS = Parameter.__table__
PARAMETER_NODES = ParameterNode.__table__
PARAMETER_TREE_CHILDREN = ParameterTreeChild.__table__


def _versions(version_ids: Sequence[UUID]) -> sa.Select:
    return (
        sa.select(MODEL_VERSIONS.c.id, MODELS.c.name, MODEL_VERSIONS.c.version)
        .select_from(
            MODEL_VERSIONS.join(MODELS, MODELS.c.id == MODEL_VERSIONS.c.model_id)
        )
        .where(MODEL_VERSIONS.c.id.in_(version_ids))
        .order_by(MODELS.c.name, MODEL_VERSIONS.c.version)
    )


def _stored_nodes(connection: Connection, version_id: UUID) -> list[TreeNodeSource]:
    return [
        TreeNodeSource(name=row.name, label=row.label)
        for row in connection.execute(
            sa.select(PARAMETER_NODES.c.name, PARAMETER_NODES.c.label).where(
                PARAMETER_NODES.c.tax_benefit_model_version_id == version_id
            )
        )
    ]


def _stored_parameters(
    connection: Connection, version_id: UUID
) -> list[TreeParameterSource]:
    return [
        TreeParameterSource(
            id=row.id,
            name=row.name,
            label=row.label,
            economy=row.economy,
            household=row.household,
        )
        for row in connection.execute(
            sa.select(
                PARAMETERS.c.id,
                PARAMETERS.c.name,
                PARAMETERS.c.label,
                PARAMETERS.c.economy,
                PARAMETERS.c.household,
            ).where(PARAMETERS.c.tax_benefit_model_version_id == version_id)
        )
    ]


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
    version_ids: Sequence[UUID],
) -> tuple[tuple[str, str, int], ...]:
    """Write the tree of each catalog version just published.

    Returns the model name, version and number of rows written for each
    version, in model and version order. Runs inside publication's
    transaction and advisory lock, after the versions' parameters and nodes
    are stored.
    """
    written = []
    for version_id, model_name, version in connection.execute(
        _versions(version_ids)
    ).all():
        rows = build_parameter_tree(
            nodes=_stored_nodes(connection, version_id),
            parameters=_stored_parameters(connection, version_id),
        )
        count = copy_rows(
            connection,
            table=PARAMETER_TREE_CHILDREN,
            rows=_table_rows(version_id, rows),
        )
        written.append((model_name, version, count))
    return tuple(written)


def assert_parameter_trees_written(
    connection: Connection,
    version_ids: Sequence[UUID],
) -> None:
    """Raise CatalogPublicationError if a version just published has no tree."""
    for version_id, model_name, version in connection.execute(
        _versions(version_ids)
    ).all():
        has_tree = connection.execute(
            sa.select(
                sa.exists().where(
                    PARAMETER_TREE_CHILDREN.c.tax_benefit_model_version_id == version_id
                )
            )
        ).scalar_one()
        if not has_tree:
            msg = (
                f"the published catalog version {version} of {model_name} "
                "has no parameter tree"
            )
            raise CatalogPublicationError(msg)
