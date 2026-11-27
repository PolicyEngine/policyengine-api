"""Framework-independent data the dynamic parameter reads exchange."""

from __future__ import annotations

from dataclasses import dataclass

from policyengine_api.services.v2.metadata.types import (
    MetadataCatalogParameter,
    StrictResponseModel,
)


@dataclass(frozen=True)
class DynamicParameterTreeLevel:
    """Which level of a catalog version's dynamic parameter tree a listing reads.

    ``parent_path`` names the node whose direct children are listed ("" for
    the top level: ``gov``, plus ``simulation`` for the US); ``settable`` keeps
    only the children a dynamic may set (a dynamic parameter whose economy or
    household flag is true, and every node above one), sorted by label, with
    child counts that count only those.
    """

    parent_path: str = ""
    settable: bool = False


class MetadataCatalogDynamicParametersResult(StrictResponseModel):
    """Every dynamic parameter of one catalog version, in name order.

    Each parameter carries its catalog ID, which ``POST /v2/dynamics`` takes,
    its economy and household flags and its current-law values in start-date
    order. node_labels maps each ancestor of a parameter that the version
    stores as a parameter node to the node's stored label (null when it has
    none), for breadcrumbs and grouping; a bracket index such as ``rates[0]``
    counts as a child of its schedule ``rates``.
    """

    policyengine_version: str
    catalog_format: int | None
    parameters: list[MetadataCatalogParameter]
    node_labels: dict[str, str | None]
