"""Database reads for direct parameter-tree children."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import col

from policyengine_api.data.v2.metadata.read_models import (
    MetadataParameterChild,
    MetadataParameterSummary,
)
from policyengine_api.data.v2.models import Parameter, ParameterNode


def _escaped_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _path_segment(remainder: Any, dialect: str) -> Any:
    dot_position = (
        sa.func.instr(remainder, ".")
        if dialect == "sqlite"
        else sa.func.strpos(remainder, ".")
    )
    return sa.case(
        (dot_position > 0, sa.func.substr(remainder, 1, dot_position - 1)),
        else_=remainder,
    )


def _child_path(column: Any, prefix: str, dialect: str) -> Any:
    remainder = sa.func.substr(column, len(prefix) + 1)
    return sa.literal(prefix) + _path_segment(remainder, dialect)


def _direct_child_path(
    column: Any,
    parent_path: Any,
    dialect: str,
) -> Any:
    remainder = sa.func.substr(column, sa.func.length(parent_path) + 2)
    return parent_path + "." + _path_segment(remainder, dialect)


def _has_path_prefix(column: Any, parent_path: Any) -> Any:
    return (
        sa.func.substr(column, 1, sa.func.length(parent_path) + 1) == parent_path + "."
    )


def parameter_children_query(
    *,
    model_version_id: UUID,
    parent_path: str,
    dialect: str,
    offset: int,
    limit: int,
) -> Any:
    """Build one bounded query for a parameter path's direct children."""

    prefix = f"{parent_path}." if parent_path else ""
    escaped_prefix = _escaped_like(prefix)
    node_name = col(ParameterNode.name)
    node_model_version_id = col(ParameterNode.tax_benefit_model_version_id)
    parameter_name = col(Parameter.name)
    parameter_model_version_id = col(Parameter.tax_benefit_model_version_id)
    node_child_path = _child_path(node_name, prefix, dialect)
    parameter_child_path = _child_path(parameter_name, prefix, dialect)
    paths = sa.union(
        sa.select(node_child_path.label("path")).where(
            node_model_version_id == model_version_id,
            node_name.like(f"{escaped_prefix}%", escape="\\"),
        ),
        sa.select(parameter_child_path.label("path")).where(
            parameter_model_version_id == model_version_id,
            parameter_name.like(f"{escaped_prefix}%", escape="\\"),
        ),
    ).subquery()
    direct_child_paths = sa.union(
        sa.select(
            _direct_child_path(
                node_name,
                paths.c.path,
                dialect,
            ).label("path")
        )
        .where(
            node_model_version_id == model_version_id,
            _has_path_prefix(node_name, paths.c.path),
        )
        .correlate(paths),
        sa.select(
            _direct_child_path(
                parameter_name,
                paths.c.path,
                dialect,
            ).label("path")
        )
        .where(
            parameter_model_version_id == model_version_id,
            _has_path_prefix(parameter_name, paths.c.path),
        )
        .correlate(paths),
    ).subquery()
    direct_child_count = (
        sa.select(sa.func.count())
        .select_from(direct_child_paths)
        .correlate(paths)
        .scalar_subquery()
    )
    parameter_id = col(Parameter.id)
    is_node = sa.or_(direct_child_count > 0, parameter_id.is_(None))
    return (
        sa.select(
            paths.c.path,
            sa.func.coalesce(
                col(ParameterNode.label),
                col(Parameter.label),
            ).label("label"),
            sa.case((is_node, "node"), else_="parameter").label("type"),
            sa.case((is_node, direct_child_count), else_=None).label("child_count"),
            parameter_id.label("parameter_id"),
            col(Parameter.label).label("parameter_label"),
            col(Parameter.description).label("parameter_description"),
            col(Parameter.data_type).label("parameter_data_type"),
            col(Parameter.unit).label("parameter_unit"),
        )
        .select_from(
            paths.outerjoin(
                ParameterNode,
                sa.and_(
                    node_name == paths.c.path,
                    node_model_version_id == model_version_id,
                ),
            ).outerjoin(
                Parameter,
                sa.and_(
                    parameter_name == paths.c.path,
                    parameter_model_version_id == model_version_id,
                ),
            )
        )
        .order_by(paths.c.path)
        .offset(offset)
        .limit(limit + 1)
    )


def parameter_children_from_rows(rows: list[Any]) -> list[MetadataParameterChild]:
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
