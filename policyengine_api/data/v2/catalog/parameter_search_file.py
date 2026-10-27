"""Each catalog version's parameter search file: what v3's search reads.

v3's parameter search (the app's ``parameterSearch.ts``) indexes every
parameter a reform can change by its path, label, unit and description, and
offers only those whose current value a draft can edit: a number, a yes/no
value or an infinite threshold. Its breadcrumbs and schedule names read the
labels of the nodes above a parameter, and its concept clusters, acronym
aliases and member labels also read the label of every other parameter under
``gov``. The file holds exactly those fields for one catalog version, so the
search runs without the catalog's values.

Labels are the stored labels, or null when none is stored. The search treats
a label equal to the path's last key as a placeholder, so a reader applies
v1's fallback itself (the key with underscores as spaces, "bracket N" for a
bracket) rather than a display label made here.

Whether a value can be edited depends on the date, because a bracket that
stops applying has a null value from that date. The file states editability
for the earliest value and the dates from which it changes, so its content
never depends on the day it was built.

Catalog publication builds the file from the installed packages' catalog
(``country_search_file``) for the version it publishes.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from policyengine_api.data.v2.catalog.parameter_tree import (
    REFORM_TREE_PREFIX,
    TreeNodeSource,
    is_reform_changeable,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from datetime import date

    from policyengine_api.data.v2.catalog.records import (
        CountryCatalog,
        ParameterRecord,
    )

PARAMETER_SEARCH_FILE_FORMAT = 1

# Repeated builds of the same rows must give the same bytes, so the gzip header
# carries no timestamp.
_GZIP_MTIME = 0
_GZIP_LEVEL = 9
# v3's draft editor accepts these two text values as numbers.
_INFINITE_VALUES = frozenset({"Infinity", "-Infinity"})


@dataclass(frozen=True, slots=True)
class SearchParameterSource:
    """A stored parameter's search fields and flags."""

    name: str
    label: str | None
    unit: str | None
    description: str | None
    economy: bool | None
    household: bool | None


@dataclass(frozen=True, slots=True)
class EditabilityChange:
    """Whether a parameter's current-law value from ``start_date`` can be edited.

    A value can be edited in a draft when it is a number, a yes/no value or the
    text "Infinity" or "-Infinity", as v3's draft editor decides.
    """

    parameter_name: str
    start_date: date
    editable: bool


class EditabilityChangeEntry(TypedDict):
    """From ``start_date`` (an ISO date), whether a draft can edit the value."""

    start_date: str
    editable: bool


class _SearchFileParameterFields(TypedDict):
    path: str
    label: str | None
    unit: str | None
    description: str | None
    editable: bool


class SearchFileParameterEntry(_SearchFileParameterFields, total=False):
    """A parameter a reform can change, as the file lists it.

    ``editable_changes`` is present only when editability changes over time.
    """

    editable_changes: list[EditabilityChangeEntry]


class SearchFileLabelEntry(TypedDict):
    """Another parameter under ``gov``: its path and stored label, or null."""

    path: str
    label: str | None


class SearchFileNodeEntry(TypedDict):
    """``gov`` or a node under it that has a stored label."""

    path: str
    label: str


class ParameterSearchFileDocument(TypedDict):
    """One catalog version's search file, each list ordered by path."""

    format: int
    country_id: str
    policyengine_version: str
    parameters: list[SearchFileParameterEntry]
    other_parameters: list[SearchFileLabelEntry]
    nodes: list[SearchFileNodeEntry]


@dataclass(frozen=True, slots=True)
class EncodedParameterSearchFile:
    """A search file as stored: gzip-compressed JSON and its content hash.

    ``content_sha256`` is the SHA-256 of the uncompressed JSON, so the same
    content has the same hash whatever compression produced the bytes.
    """

    compressed_content: bytes
    content_sha256: str
    uncompressed_size: int
    compressed_size: int


def _editability(
    changes: Iterable[EditabilityChange],
) -> dict[str, tuple[bool, list[EditabilityChangeEntry]]]:
    """Return each parameter's earliest editability and the later changes."""
    by_parameter: defaultdict[str, list[EditabilityChange]] = defaultdict(list)
    for change in changes:
        by_parameter[change.parameter_name].append(change)
    editability: dict[str, tuple[bool, list[EditabilityChangeEntry]]] = {}
    for name, parameter_changes in by_parameter.items():
        ordered = sorted(parameter_changes, key=lambda change: change.start_date)
        earliest = ordered[0].editable
        later: list[EditabilityChangeEntry] = []
        current = earliest
        for change in ordered[1:]:
            if change.editable != current:
                later.append(
                    {
                        "start_date": change.start_date.isoformat(),
                        "editable": change.editable,
                    }
                )
                current = change.editable
        editability[name] = (earliest, later)
    return editability


def _stored_label(label: str | None) -> str | None:
    return label if label is not None and label.strip() else None


def _is_gov_node(name: str) -> bool:
    """Return whether a node is ``gov`` itself or below it, as in v1's metadata."""
    return name == REFORM_TREE_PREFIX.rstrip(".") or name.startswith(REFORM_TREE_PREFIX)


def build_parameter_search_file(
    *,
    country_id: str,
    policyengine_version: str,
    parameters: Iterable[SearchParameterSource],
    nodes: Iterable[TreeNodeSource],
    editability: Iterable[EditabilityChange],
) -> ParameterSearchFileDocument:
    """Return one catalog version's search file, ordered by path.

    ``parameters`` lists every parameter a reform can change with its search
    fields and editability; ``other_parameters`` lists the other parameters
    under ``gov`` with their labels; ``nodes`` lists ``gov`` and every node
    under it that has a stored label. A parameter without current-law values cannot be
    edited.
    """
    editability_by_name = _editability(editability)
    changeable: list[SearchFileParameterEntry] = []
    others: list[SearchFileLabelEntry] = []
    for parameter in sorted(parameters, key=lambda parameter: parameter.name):
        if not parameter.name.startswith(REFORM_TREE_PREFIX):
            continue
        label = _stored_label(parameter.label)
        if not is_reform_changeable(
            parameter.name, economy=parameter.economy, household=parameter.household
        ):
            others.append({"path": parameter.name, "label": label})
            continue
        editable, changes = editability_by_name.get(parameter.name, (False, []))
        entry: SearchFileParameterEntry = {
            "path": parameter.name,
            "label": label,
            "unit": parameter.unit,
            "description": parameter.description,
            "editable": editable,
        }
        if changes:
            entry["editable_changes"] = changes
        changeable.append(entry)
    labelled_nodes: list[SearchFileNodeEntry] = [
        {"path": node.name, "label": node.label}
        for node in sorted(nodes, key=lambda node: node.name)
        if _is_gov_node(node.name) and node.label is not None and node.label.strip()
    ]
    return {
        "format": PARAMETER_SEARCH_FILE_FORMAT,
        "country_id": country_id,
        "policyengine_version": policyengine_version,
        "parameters": changeable,
        "other_parameters": others,
        "nodes": labelled_nodes,
    }


def encode_parameter_search_file(
    search_file: ParameterSearchFileDocument,
) -> EncodedParameterSearchFile:
    """Return the file as compact UTF-8 JSON, gzip-compressed, with its hash."""
    content = json.dumps(
        search_file, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    compressed = gzip.compress(content, compresslevel=_GZIP_LEVEL, mtime=_GZIP_MTIME)
    return EncodedParameterSearchFile(
        compressed_content=compressed,
        content_sha256=hashlib.sha256(content).hexdigest(),
        uncompressed_size=len(content),
        compressed_size=len(compressed),
    )


def is_editable_value(value: object) -> bool:
    """Return whether a draft can edit a value, as v3's draft editor decides.

    A number (an infinite threshold, stored as the text "Infinity" or
    "-Infinity", included) or a yes/no value can be edited; a list of variable
    names, other text and a missing value cannot.
    """
    if isinstance(value, bool | int | float):
        return True
    return isinstance(value, str) and value in _INFINITE_VALUES


def _parameter_editability(parameter: ParameterRecord) -> Iterator[EditabilityChange]:
    """Yield the parameter's first value's editability and each later change."""
    previous: bool | None = None
    for value in sorted(parameter.values, key=lambda value: value.start_date):
        editable = is_editable_value(value.value_json)
        if editable != previous:
            yield EditabilityChange(
                parameter_name=parameter.name,
                start_date=value.start_date.date(),
                editable=editable,
            )
            previous = editable


def country_search_file(country: CountryCatalog) -> ParameterSearchFileDocument:
    """Return the search file of a country's catalog version from its records."""
    return build_parameter_search_file(
        country_id=country.country_id,
        policyengine_version=country.model_version.version,
        parameters=(
            SearchParameterSource(
                name=parameter.name,
                label=parameter.label,
                unit=parameter.unit,
                description=parameter.description,
                economy=parameter.economy,
                household=parameter.household,
            )
            for parameter in country.parameters
        ),
        nodes=(
            TreeNodeSource(name=node.name, label=node.label)
            for node in country.parameter_nodes
        ),
        editability=(
            change
            for parameter in country.parameters
            for change in _parameter_editability(parameter)
        ),
    )
