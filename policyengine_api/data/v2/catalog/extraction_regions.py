"""Build region records from scoped reference regions, and check their datasets."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.extraction_values import (
    CatalogExtractionError,
    catalog_identifier,
)
from policyengine_api.data.v2.catalog.records import RegionRecord

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from policyengine_api.data.v2.catalog.region_scoping import ScopedRegion

DATASET_YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")


def dataset_year(name: str) -> int:
    """Return the last four-digit year in a dataset name; raise if it has none."""
    matches = DATASET_YEAR_PATTERN.findall(name)
    if not matches:
        msg = f"dataset {name!r} has no four-digit year"
        raise CatalogExtractionError(msg)
    match = list(DATASET_YEAR_PATTERN.finditer(name))[-1]
    return int(match.group())


def release_default_dataset(country_id: str, release_manifest: object) -> str:
    """Return the default dataset the installed PolicyEngine.py release names.

    The Public API sets no default of its own; region scoping then requires the
    release to certify it.
    """
    default_dataset = getattr(release_manifest, "default_dataset", None)
    if not isinstance(default_dataset, str) or not default_dataset:
        msg = f"{country_id} release manifest names no default dataset"
        raise CatalogExtractionError(msg)
    return default_dataset


def normalize_region(
    scoped_region: ScopedRegion,
    *,
    model_version_id: UUID,
    dataset_ids: Mapping[str, UUID],
) -> RegionRecord:
    """Build one region's record from its reference, dataset and filter."""
    reference = scoped_region.reference
    requires_filter = scoped_region.filter_strategy is not None
    return RegionRecord(
        id=catalog_identifier("region", model_version_id, reference.code),
        model_version_id=model_version_id,
        default_dataset_id=dataset_ids[scoped_region.dataset_name],
        code=reference.code,
        label=reference.label,
        region_type=reference.region_type,
        requires_filter=requires_filter,
        filter_field=scoped_region.filter_field,
        filter_value=reference.filter_value if requires_filter else None,
        filter_strategy=scoped_region.filter_strategy,
        parent_code=reference.parent_code,
        state_code=reference.state_code,
        state_name=reference.state_name,
    )
