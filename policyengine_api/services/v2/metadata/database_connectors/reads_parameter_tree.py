"""Database selections for one level of a catalog version's parameter tree."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlmodel import Session, col

from policyengine_api.data.v2.models import Parameter, ParameterTreeChild
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.metadata.types import ParameterTreeLevel


def _parameter_children_statement(
    *,
    model_version_id: UUID,
    level: ParameterTreeLevel,
    offset: int,
    limit: int,
) -> sa.Select[Any]:
    position = (
        col(ParameterTreeChild.reform_position)
        if level.reform_changeable
        else col(ParameterTreeChild.position)
    )
    child_count = (
        col(ParameterTreeChild.reform_child_count)
        if level.reform_changeable
        else col(ParameterTreeChild.child_count)
    )
    statement: sa.Select[Any] = (
        sa.select(
            col(ParameterTreeChild.path).label("path"),
            col(ParameterTreeChild.label).label("label"),
            col(ParameterTreeChild.child_type).label("type"),
            child_count.label("child_count"),
            Parameter,
        )
        .select_from(ParameterTreeChild)
        .outerjoin(
            Parameter,
            col(Parameter.id) == col(ParameterTreeChild.parameter_id),
        )
        .where(
            col(ParameterTreeChild.tax_benefit_model_version_id) == model_version_id,
            col(ParameterTreeChild.parent_path) == level.parent_path,
        )
    )
    if level.reform_changeable:
        statement = statement.where(position.is_not(None))
    return statement.order_by(position).offset(offset).limit(limit + 1)


def read_parameter_children(
    session: Session,
    *,
    model_version_id: UUID,
    level: ParameterTreeLevel,
    offset: int,
    limit: int,
) -> list[Any]:
    """Return a page of the level's direct children from the stored tree.

    One read of a listing index: every child in tree order, or for a
    reform-changeable level only the children a reform can change, in label order,
    with child counts that count only those. Each row has the child's path,
    label, type (node or parameter), child count and the stored Parameter
    (None for a node); limit + 1 rows are fetched so the caller can tell
    whether another page exists.
    """
    return read_rows(
        session,
        _parameter_children_statement(
            model_version_id=model_version_id,
            level=level,
            offset=offset,
            limit=limit,
        ),
    )


def read_parameter_tree_written(session: Session, *, model_version_id: UUID) -> bool:
    """Return whether the version's parameter tree has any stored row."""
    rows = read_rows(
        session,
        sa.select(
            sa.exists().where(
                col(ParameterTreeChild.tax_benefit_model_version_id) == model_version_id
            )
        ),
    )
    return bool(rows[0][0])
