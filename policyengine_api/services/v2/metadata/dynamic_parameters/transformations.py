"""Pure conversions for the dynamic parameter reads.

The dynamic parameter tree is built on each request with
``parameter_tree.build_parameter_tree``, from the version's dynamic
parameters, the stored labels of their ancestor nodes and the labels the
version's enum variables give each enum value, so its labels and order follow
the policy tree's rules. ``is_dynamic_settable_parameter`` decides which
parameters the settable level keeps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.parameter_tree import (
    TreeNodeSource,
    TreeParameterSource,
    build_parameter_tree,
    enum_labels_by_value,
    is_dynamic_settable_parameter,
)
from policyengine_api.services.v2.metadata.dynamic_parameters.types import (
    MetadataCatalogDynamicParametersResult,
)
from policyengine_api.services.v2.metadata.transformations import (
    ancestor_paths,
    metadata_parameter,
)
from policyengine_api.services.v2.metadata.types import (
    MetadataCanonicalParameterValue,
    MetadataCatalogParameter,
    MetadataDatedValue,
    MetadataParameterChild,
    ParameterNodeLabelRow,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from policyengine_api.data.v2.catalog.catalog_selection_validation import (
        SelectedCatalog,
    )
    from policyengine_api.data.v2.catalog.parameter_tree import (
        ParameterTreeChildRow,
    )
    from policyengine_api.data.v2.models import (
        DynamicParameter,
        DynamicParameterValue,
    )
    from policyengine_api.data.v2.models.metadata import CatalogEnumValue
    from policyengine_api.services.v2.metadata.dynamic_parameters.types import (
        DynamicParameterTreeLevel,
    )


def metadata_dynamic_parameter_value(
    value: DynamicParameterValue,
) -> MetadataCanonicalParameterValue:
    """Return a stored current-law dynamic value as the API represents a value.

    ``parameter_id`` is the dynamic parameter's catalog ID.
    """
    return MetadataCanonicalParameterValue(
        id=value.id,
        parameter_id=value.dynamic_parameter_id,
        value=value.value_json,
        start_date=value.start_date,
        end_date=value.end_date,
    )


def ancestor_node_names(parameters: Sequence[DynamicParameter]) -> set[str]:
    """Return the path of every node above any of the parameters."""
    return {
        ancestor
        for parameter in parameters
        for ancestor in ancestor_paths(parameter.name)
    }


def dynamic_parameter_tree(
    *,
    parameters: Sequence[DynamicParameter],
    node_rows: Sequence[ParameterNodeLabelRow],
    enum_value_lists: Sequence[Sequence[CatalogEnumValue]],
) -> tuple[ParameterTreeChildRow, ...]:
    """Build a version's dynamic parameter tree.

    ``node_rows`` are the stored labels of the parameters' ancestor nodes,
    so the tree holds only the dynamic parameters and the nodes above them,
    and ``enum_value_lists`` the enum values of each of the version's enum
    variables. The rows' ``reform_*`` fields describe the parameters a dynamic
    may set.
    """
    return build_parameter_tree(
        nodes=[TreeNodeSource(name=row.name, label=row.label) for row in node_rows],
        parameters=[
            TreeParameterSource(
                id=parameter.id,
                name=parameter.name,
                label=parameter.label,
                economy=parameter.economy,
                household=parameter.household,
            )
            for parameter in parameters
        ],
        enum_labels=enum_labels_by_value(
            (enum_value["value"], enum_value["label"])
            for enum_values in enum_value_lists
            for enum_value in enum_values
        ),
        is_changeable=is_dynamic_settable_parameter,
    )


def dynamic_parameter_children(
    tree_rows: Sequence[ParameterTreeChildRow],
    *,
    parameters: Sequence[DynamicParameter],
    level: DynamicParameterTreeLevel,
    offset: int,
    limit: int,
) -> list[MetadataParameterChild]:
    """Return up to limit + 1 children of the level, from offset on.

    Without ``settable``, every child in tree order (path order, with a
    schedule's brackets in bracket order); with it, only the children a
    dynamic may set, in label order, with child counts that count only those.
    A parameter leaf carries the same summary as the parameter routes.
    """
    siblings = [row for row in tree_rows if row.parent_path == level.parent_path]
    if level.settable:
        ordered = sorted(
            (row for row in siblings if row.reform_position is not None),
            key=lambda row: row.reform_position or 0,
        )
    else:
        ordered = sorted(siblings, key=lambda row: row.position)
    parameters_by_id = {parameter.id: parameter for parameter in parameters}
    return [
        MetadataParameterChild(
            path=row.path,
            label=row.label,
            type=row.child_type,
            child_count=(row.reform_child_count if level.settable else row.child_count),
            parameter=(
                None
                if row.parameter_id is None
                else metadata_parameter(parameters_by_id[row.parameter_id])
            ),
        )
        for row in ordered[offset : offset + limit + 1]
    ]


def metadata_catalog_dynamic_parameters(
    selected: SelectedCatalog,
    *,
    parameters: Sequence[DynamicParameter],
    values_by_name: dict[str, list[MetadataDatedValue]],
    node_rows: Sequence[ParameterNodeLabelRow],
) -> MetadataCatalogDynamicParametersResult:
    """Build the version's whole dynamic parameter category.

    values_by_name maps each parameter's name to its current-law values
    (``dated_values_by_parameter_name``), and node_rows are the stored labels
    of the parameters' ancestor nodes.
    """
    return MetadataCatalogDynamicParametersResult(
        policyengine_version=selected.policyengine_version,
        catalog_format=selected.model_version.catalog_format,
        parameters=[
            MetadataCatalogParameter(
                **metadata_parameter(parameter).model_dump(),
                values=values_by_name[parameter.name],
            )
            for parameter in parameters
        ],
        node_labels={row.name: row.label for row in node_rows},
    )
