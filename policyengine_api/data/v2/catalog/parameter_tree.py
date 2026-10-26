"""Each catalog version's parameter tree, as rows of direct children.

The tree is derived from a version's stored parameters and parameter nodes
alone, and is written when a version is published. Every node and parameter
of the version is one row, under the path of its parent (the empty string for
top-level paths).

A ``[`` starts a child as a ``.`` does: a bracket schedule such as
``gov.hmrc.income_tax.rates.uk`` is one node whose children are its brackets
``uk[0]``, ``uk[1]`` and so on, labelled "Bracket 1", "Bracket 2"; a bracket's
own children (``rate``, ``threshold``) are unchanged. Labels take the form
the app's newer interface (v3) shows, in every view: a stored label with its
underscores as spaces and its first letter upper-cased, or, for a path with no
stored label, the last part of its name in the same form.

Each row also records whether a reform can change it, which mirrors the tree
the app's newer interface builds from v1 metadata
(``app/src/libs/buildParameterTree.ts``): a parameter under ``gov`` whose
economy or household flag is set and whose path names neither ``taxsim``,
``gov.abolitions`` nor ``pycache``, and every node with such a parameter
below it. A version published before catalog format 2 has no flags, so only
the path rules apply to it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

REFORM_TREE_PREFIX = "gov."
REFORM_EXCLUDED_PATH_PARTS = ("taxsim", "gov.abolitions", "pycache")

_BRACKET_INDEX = re.compile(r"\[(\d+)\]$")
_NAME_PARTS = re.compile(r"[.\[]")

ChildType = Literal["node", "parameter"]


@dataclass(frozen=True, slots=True)
class TreeNodeSource:
    """A stored parameter node: its name and stored label."""

    name: str
    label: str | None


@dataclass(frozen=True, slots=True)
class TreeParameterSource:
    """A stored parameter: its ID, name, stored label and flags."""

    id: UUID
    name: str
    label: str | None
    economy: bool | None
    household: bool | None


@dataclass(frozen=True, slots=True)
class ParameterTreeChildRow:
    """One direct child in a version's parameter tree.

    ``position`` orders the children of one parent; ``reform_position`` orders
    only those a reform can change and is None for the others. Node rows carry
    their direct child counts (all children, and those a reform can change);
    parameter rows carry the parameter's ID and flags instead.
    """

    parent_path: str
    path: str
    position: int
    label: str
    child_type: ChildType
    child_count: int | None
    reform_changeable: bool
    reform_position: int | None
    reform_child_count: int | None
    parameter_id: UUID | None
    economy: bool | None
    household: bool | None


def parent_path(path: str) -> str:
    """Return the path of a node's or parameter's parent, or "" at the top."""
    delimiter_index = max(path.rfind("."), path.rfind("["))
    return path[:delimiter_index] if delimiter_index > 0 else ""


def bracket_index(path: str) -> int | None:
    """Return the index of a bracket path such as ``rates.uk[0]``, else None."""
    match = _BRACKET_INDEX.search(path)
    return int(match.group(1)) if match else None


def display_label(label: str) -> str:
    """Return a label as v3 shows it: underscores as spaces, first letter upper."""
    words = label.replace("_", " ")
    return words[:1].upper() + words[1:]


def generated_label(path: str) -> str:
    """Return a label made from the last part of a name, as v3 makes one."""
    return display_label(_NAME_PARTS.split(path)[-1])


def _child_label(path: str, stored_label: str | None) -> str:
    index = bracket_index(path)
    if index is not None:
        return f"Bracket {index + 1}"
    if stored_label and stored_label.strip():
        return display_label(stored_label)
    return generated_label(path)


def is_reform_changeable_parameter(parameter: TreeParameterSource) -> bool:
    """Return whether a reform can change this parameter, as v3's tree decides."""
    if not parameter.name.startswith(REFORM_TREE_PREFIX):
        return False
    if any(part in parameter.name for part in REFORM_EXCLUDED_PATH_PARTS):
        return False
    if parameter.economy is None and parameter.household is None:
        return True
    return bool(parameter.economy) or bool(parameter.household)


def _ancestors(path: str) -> list[str]:
    ancestors = []
    current = parent_path(path)
    while current:
        ancestors.append(current)
        current = parent_path(current)
    return ancestors


def _position_key(path: str) -> tuple[int, int, str]:
    index = bracket_index(path)
    if index is not None:
        return (0, index, "")
    return (1, 0, path)


def _reform_position_key(path: str, label: str) -> tuple[int, int, str, str]:
    index = bracket_index(path)
    if index is not None:
        return (0, index, "", "")
    return (1, 0, label.casefold(), path)


@dataclass(frozen=True, slots=True)
class _TreeIndex:
    """The maps a version's tree rows are built from."""

    children: dict[str, list[str]]
    labels: dict[str, str]
    changeable: frozenset[str]
    parameters_by_path: dict[str, TreeParameterSource]

    def row(
        self, path: str, *, parent: str, position: int, reform_position: int | None
    ) -> ParameterTreeChildRow:
        direct_children = self.children.get(path, [])
        parameter = self.parameters_by_path.get(path)
        leaf = parameter if parameter is not None and not direct_children else None
        return ParameterTreeChildRow(
            parent_path=parent,
            path=path,
            position=position,
            label=self.labels[path],
            child_type="node" if leaf is None else "parameter",
            child_count=len(direct_children) if leaf is None else None,
            reform_changeable=path in self.changeable,
            reform_position=reform_position,
            reform_child_count=(
                sum(child in self.changeable for child in direct_children)
                if leaf is None
                else None
            ),
            parameter_id=None if leaf is None else leaf.id,
            economy=None if leaf is None else leaf.economy,
            household=None if leaf is None else leaf.household,
        )


def _stored_label(
    path: str,
    stored_labels: dict[str, str | None],
    parameters_by_path: dict[str, TreeParameterSource],
) -> str | None:
    if path in stored_labels:
        return stored_labels[path]
    parameter = parameters_by_path.get(path)
    return None if parameter is None else parameter.label


def build_parameter_tree(
    *,
    nodes: Iterable[TreeNodeSource],
    parameters: Iterable[TreeParameterSource],
) -> tuple[ParameterTreeChildRow, ...]:
    """Return one row per node and parameter of a version, parents first."""
    parameters_by_path = {parameter.name: parameter for parameter in parameters}
    stored_labels = {node.name: node.label for node in nodes}
    paths = set(stored_labels) | set(parameters_by_path)
    for path in list(paths):
        paths.update(_ancestors(path))
    paths.discard("")

    changeable: set[str] = set()
    for parameter in parameters_by_path.values():
        if is_reform_changeable_parameter(parameter):
            changeable.add(parameter.name)
            changeable.update(_ancestors(parameter.name))

    children: defaultdict[str, list[str]] = defaultdict(list)
    for path in paths:
        children[parent_path(path)].append(path)

    index = _TreeIndex(
        children=dict(children),
        labels={
            path: _child_label(
                path, _stored_label(path, stored_labels, parameters_by_path)
            )
            for path in paths
        },
        changeable=frozenset(changeable),
        parameters_by_path=parameters_by_path,
    )
    rows: list[ParameterTreeChildRow] = []
    for parent in sorted(index.children, key=lambda path: (path.count("."), path)):
        siblings = sorted(index.children[parent], key=_position_key)
        reform_siblings = sorted(
            (path for path in siblings if path in index.changeable),
            key=lambda path: _reform_position_key(path, index.labels[path]),
        )
        reform_positions = {path: order for order, path in enumerate(reform_siblings)}
        rows.extend(
            index.row(
                path,
                parent=parent,
                position=position,
                reform_position=reform_positions.get(path),
            )
            for position, path in enumerate(siblings)
        )
    return tuple(rows)
