"""SQL query and row conversion for direct parameter-tree children."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlmodel import select

from policyengine_api.data.v2.catalog.schemas import (
    MetadataParameterChild,
    MetadataParameterSummary,
)
from policyengine_api.data.v2.models import Parameter, ParameterNode


def _escaped_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _child_path(column: object, prefix: str, dialect: str) -> object:
    remainder = sa.func.substr(column, len(prefix) + 1)
    dot_position = (
        sa.func.instr(remainder, ".")
        if dialect == "sqlite"
        else sa.func.strpos(remainder, ".")
    )
    segment = sa.case(
        (dot_position > 0, sa.func.substr(remainder, 1, dot_position - 1)),
        else_=remainder,
    )
    return sa.literal(prefix) + segment


def parameter_children_query(
    *,
    model_version_id: UUID,
    parent_path: str,
    dialect: str,
    offset: int,
    limit: int,
) -> object:
    """Build one bounded query for a parameter path's direct children."""

    prefix = f"{parent_path}." if parent_path else ""
    escaped_prefix = _escaped_like(prefix)
    node_child_path = _child_path(ParameterNode.name, prefix, dialect)
    parameter_child_path = _child_path(Parameter.name, prefix, dialect)
    paths = sa.union(
        select(node_child_path.label("path")).where(
            ParameterNode.tax_benefit_model_version_id == model_version_id,
            ParameterNode.name.like(f"{escaped_prefix}%", escape="\\"),
        ),
        select(parameter_child_path.label("path")).where(
            Parameter.tax_benefit_model_version_id == model_version_id,
            Parameter.name.like(f"{escaped_prefix}%", escape="\\"),
        ),
    ).subquery()
    descendant_count = (
        select(sa.func.count(Parameter.id))
        .where(
            Parameter.tax_benefit_model_version_id == model_version_id,
            sa.func.substr(
                Parameter.name,
                1,
                sa.func.length(paths.c.path) + 1,
            )
            == paths.c.path + ".",
        )
        .correlate(paths)
        .scalar_subquery()
    )
    is_node = sa.or_(descendant_count > 0, Parameter.id.is_(None))
    return (
        select(
            paths.c.path,
            sa.func.coalesce(ParameterNode.label, Parameter.label).label("label"),
            sa.case((is_node, "node"), else_="parameter").label("type"),
            sa.case((is_node, descendant_count), else_=None).label("child_count"),
            Parameter.id.label("parameter_id"),
            Parameter.label.label("parameter_label"),
            Parameter.description.label("parameter_description"),
            Parameter.data_type.label("parameter_data_type"),
            Parameter.unit.label("parameter_unit"),
        )
        .select_from(
            paths.outerjoin(
                ParameterNode,
                sa.and_(
                    ParameterNode.name == paths.c.path,
                    ParameterNode.tax_benefit_model_version_id == model_version_id,
                ),
            ).outerjoin(
                Parameter,
                sa.and_(
                    Parameter.name == paths.c.path,
                    Parameter.tax_benefit_model_version_id == model_version_id,
                ),
            )
        )
        .order_by(paths.c.path)
        .offset(offset)
        .limit(limit + 1)
    )


def parameter_children_from_rows(rows: list) -> list[MetadataParameterChild]:
    """Convert parameter-tree query rows into typed direct-child records."""

    items = []
    for row in rows:
        parameter = None
        if row.type == "parameter":
            parameter = MetadataParameterSummary(
                id=row.parameter_id,
                name=row.path,
                label=row.parameter_label,
                description=row.parameter_description,
                data_type=row.parameter_data_type,
                unit=row.parameter_unit,
            )
        items.append(
            MetadataParameterChild(
                path=row.path,
                label=row.label or row.path.rsplit(".", 1)[-1],
                type=row.type,
                child_count=row.child_count,
                parameter=parameter,
            )
        )
    return items
