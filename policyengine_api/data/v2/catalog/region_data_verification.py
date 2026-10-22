"""Refuse to publish regions whose households the certified data cannot select.

A row-filtered region needs its filter column among the household columns of
its dataset. A weight-replacement region needs a row in its weight matrix: the
matrix's rows follow the order of the row lookup that compute uses to find a
region's row, so the lookup must list exactly as many codes as the matrix has
rows and include the region's code. The release certifies no lookup file, so
the Public API's own copies of the lookups stand in for it.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar

from policyengine_api.data.v2.catalog.errors import (
    CatalogExtractionError,
    CertifiedDataReadError,
)
from policyengine_api.data.v2.catalog.region_scoping import (
    ROW_FILTER,
    WEIGHT_REPLACEMENT,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from policyengine_api.data.v2.catalog.records import (
        CertifiedArtifact,
        CountryCatalog,
        NormalizedCatalog,
        RegionRecord,
    )

# The Public API's own copies of the row lookups compute reads to find a
# region's row in each UK weight matrix. The certified data release lists no
# lookup file, so the matrix check compares each matrix with these copies. On
# 2026-10-22 both copies were checked to be identical in content to the lookups
# the calculation workers download.
_DATA_DIRECTORY = Path(__file__).parents[2]
WEIGHT_MATRIX_ROW_LOOKUPS: Mapping[str, Path] = {
    "parliamentary_constituency_weights": _DATA_DIRECTORY / "constituencies_2024.csv",
    "local_authority_weights": _DATA_DIRECTORY / "local_authorities_2021.csv",
}
# Region codes named in an error message, at most.
MAX_LISTED_REGIONS = 3

_Result = TypeVar("_Result")


class RegionDataVerificationError(CatalogExtractionError):
    """Raised when the certified data cannot select a region's households."""


class CertifiedDataInspector(Protocol):
    """Reads what verification needs from one certified artifact."""

    def household_columns(self, artifact: CertifiedArtifact) -> frozenset[str]:
        """Return the household column names of a dataset artifact."""
        ...

    def weight_matrix_row_count(self, artifact: CertifiedArtifact) -> int:
        """Return how many region rows a weight-matrix artifact holds."""
        ...


def load_weight_matrix_row_codes(path: Path) -> tuple[str, ...]:
    """Return a row lookup's region codes in matrix row order."""
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(row["code"] for row in csv.DictReader(handle))


def _listed(codes: Sequence[str]) -> str:
    shown = ", ".join(codes[:MAX_LISTED_REGIONS])
    more = len(codes) - MAX_LISTED_REGIONS
    return f"{shown} and {more} more" if more > 0 else shown


def _noun(count: int) -> str:
    return "region" if count == 1 else "regions"


def _read(artifact: CertifiedArtifact, read: Callable[[], _Result]) -> _Result:
    """Run one read of an artifact, reporting a failure safely.

    A structure error keeps its own message; any other failure is reduced to
    the artifact's name and the error type, since its text may hold a location.
    """
    try:
        return read()
    except RegionDataVerificationError:
        raise
    except CertifiedDataReadError as error:
        # Its message names only HDF5 entries and counts.
        msg = f"the certified artifact {artifact.name} cannot be checked: {error}"
        raise RegionDataVerificationError(msg) from error
    except Exception as error:
        # Only the artifact's name and the error type: the error text may hold
        # its location, and command output names no dataset release.
        msg = (
            f"could not read the certified artifact {artifact.name}: "
            f"{type(error).__name__}"
        )
        raise RegionDataVerificationError(msg) from error


def _verify_row_filters(
    country: CountryCatalog,
    artifacts: Mapping[str, CertifiedArtifact],
    inspector: CertifiedDataInspector,
) -> None:
    dataset_names = {dataset.id: dataset.name for dataset in country.datasets}
    regions_by_column: dict[tuple[str, str], list[str]] = defaultdict(list)
    for region in country.regions:
        if region.filter_strategy == ROW_FILTER and region.filter_field:
            dataset_name = dataset_names[region.default_dataset_id]
            regions_by_column[dataset_name, region.filter_field].append(region.code)
    columns_by_dataset: dict[str, frozenset[str]] = {}
    for (dataset_name, column), codes in sorted(regions_by_column.items()):
        if dataset_name not in columns_by_dataset:
            artifact = artifacts[dataset_name]
            columns_by_dataset[dataset_name] = _read(
                artifact,
                partial(inspector.household_columns, artifact),
            )
        if column not in columns_by_dataset[dataset_name]:
            msg = (
                f"the certified dataset {dataset_name} has no household column "
                f"{column}, which {len(codes)} {country.country_id} "
                f"{_noun(len(codes))} {'filters' if len(codes) == 1 else 'filter'} "
                f"on ({_listed(codes)})"
            )
            raise RegionDataVerificationError(msg)


def _weight_replacement_regions(
    regions: Sequence[RegionRecord],
) -> dict[str, list[RegionRecord]]:
    regions_by_matrix: dict[str, list[RegionRecord]] = defaultdict(list)
    for region in regions:
        if region.filter_strategy == WEIGHT_REPLACEMENT and region.filter_field:
            regions_by_matrix[region.filter_field].append(region)
    return regions_by_matrix


def _verify_weight_matrices(
    country: CountryCatalog,
    artifacts: Mapping[str, CertifiedArtifact],
    inspector: CertifiedDataInspector,
    weight_matrix_row_codes: Mapping[str, Sequence[str]],
) -> None:
    for matrix_name, regions in sorted(
        _weight_replacement_regions(country.regions).items()
    ):
        row_codes = weight_matrix_row_codes.get(matrix_name)
        if row_codes is None:
            msg = f"no row lookup names the regions of the weight matrix {matrix_name}"
            raise RegionDataVerificationError(msg)
        artifact = artifacts[matrix_name]
        row_count = _read(
            artifact,
            partial(inspector.weight_matrix_row_count, artifact),
        )
        if row_count != len(row_codes):
            msg = (
                f"the weight matrix {matrix_name} has {row_count} region rows, but its "
                f"row lookup lists {len(row_codes)} codes"
            )
            raise RegionDataVerificationError(msg)
        known_codes = set(row_codes)
        missing = [
            region.code for region in regions if region.filter_value not in known_codes
        ]
        if missing:
            msg = (
                f"the weight matrix {matrix_name} has no row for {len(missing)} "
                f"{country.country_id} {_noun(len(missing))} ({_listed(missing)})"
            )
            raise RegionDataVerificationError(msg)


def verify_region_data(
    catalog: NormalizedCatalog,
    inspector: CertifiedDataInspector,
    *,
    countries: Sequence[str],
    weight_matrix_row_codes: Mapping[str, Sequence[str]] | None = None,
) -> None:
    """Check the regions of the named countries against their certified artifacts.

    Each artifact is read at most once. Without explicit row codes, the row
    lookups in ``WEIGHT_MATRIX_ROW_LOOKUPS`` are read.
    """
    if weight_matrix_row_codes is None:
        weight_matrix_row_codes = {
            name: load_weight_matrix_row_codes(path)
            for name, path in WEIGHT_MATRIX_ROW_LOOKUPS.items()
        }
    for country_id in countries:
        country = catalog.country(country_id)
        artifacts = {
            artifact.name: artifact for artifact in country.certified_artifacts
        }
        _verify_row_filters(country, artifacts, inspector)
        _verify_weight_matrices(country, artifacts, inspector, weight_matrix_row_codes)
