"""Database selections for parameter-node labels."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import ParameterNode
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID


def read_parameter_node_labels(
    session: Session, *, model_version_id: UUID, node_names: Collection[str]
) -> list[Any]:
    """Return the name and stored label of each named node of a model version.

    Names the version has no node for are absent. Rows are in name order.
    """
    if not node_names:
        return []
    return read_rows(
        session,
        select(col(ParameterNode.name), col(ParameterNode.label))
        .where(
            col(ParameterNode.tax_benefit_model_version_id) == model_version_id,
            col(ParameterNode.name).in_(sorted(node_names)),
        )
        .order_by(col(ParameterNode.name)),
    )
