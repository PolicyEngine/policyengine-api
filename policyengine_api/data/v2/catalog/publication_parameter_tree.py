"""Write the parameter tree of each stored catalog version that has none.

A version's tree rows are derived from its stored parameters and parameter
nodes alone (``parameter_tree``), so a version published in the current
transaction and a version stored before the tree existed are written the same
way. Writing only inserts: a version that already has rows keeps them, and no
other table changes.
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
    from collections.abc import Iterator
    from uuid import UUID

    from sqlalchemy import Connection

MODELS = TaxBenefitModel.__table__
MODEL_VERSIONS = TaxBenefitModelVersion.__table__
PARAMETERS = Parameter.__table__
PARAMETER_NODES = ParameterNode.__table__
PARAMETER_TREE_CHILDREN = ParameterTreeChild.__table__


def _versions_without_tree() -> sa.Select:
    has_tree = sa.exists().where(
        PARAMETER_TREE_CHILDREN.c.tax_benefit_model_version_id == MODEL_VERSIONS.c.id
    )
    has_parameters_or_nodes = sa.or_(
        sa.exists().where(
            PARAMETERS.c.tax_benefit_model_version_id == MODEL_VERSIONS.c.id
        ),
        sa.exists().where(
            PARAMETER_NODES.c.tax_benefit_model_version_id == MODEL_VERSIONS.c.id
        ),
    )
    return (
        sa.select(MODEL_VERSIONS.c.id, MODELS.c.name, MODEL_VERSIONS.c.version)
        .select_from(
            MODEL_VERSIONS.join(MODELS, MODELS.c.id == MODEL_VERSIONS.c.model_id)
        )
        .where(~has_tree, has_parameters_or_nodes)
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


def write_missing_parameter_trees(
    connection: Connection,
) -> tuple[tuple[str, str, int], ...]:
    """Write the tree of every stored version that has parameters but no tree.

    Returns the model name, version and number of rows written for each
    version, in model and version order. Runs inside publication's
    transaction and advisory lock.
    """
    written = []
    for version_id, model_name, version in connection.execute(
        _versions_without_tree()
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


def assert_every_parameter_tree_written(connection: Connection) -> None:
    """Raise CatalogPublicationError if a version with parameters has no tree."""
    missing = connection.execute(_versions_without_tree()).first()
    if missing is not None:
        msg = (
            f"the stored catalog version {missing.version} of {missing.name} "
            "has no parameter tree"
        )
        raise CatalogPublicationError(msg)
