"""Refuse to publish regions whose households the certified data cannot select.

A row-filtered region needs its filter column among the household columns of
its dataset.
"""

from __future__ import annotations

from collections import defaultdict
from functools import partial
from typing import TYPE_CHECKING, Protocol, TypeVar

from policyengine_api.data.v2.catalog.errors import CertifiedDataReadError
from policyengine_api.data.v2.catalog.region_scoping import ROW_FILTER

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from policyengine_api.data.v2.catalog.records import (
        CertifiedArtifact,
        CountryCatalog,
        NormalizedCatalog,
    )

# Region codes named in an error message, at most.
MAX_LISTED_REGIONS = 3

_Result = TypeVar("_Result")


class RegionDataVerificationError(RuntimeError):
    """Raised when certified data cannot select a region's households.

    Also raised when an artifact cannot be read for that check. Verification
    runs after the stored catalog versions are read and before anything is
    published; its messages name only artifacts, columns, codes and counts.
    """


class CertifiedDataInspector(Protocol):
    """Reads what verification needs from one certified artifact."""

    def household_columns(self, artifact: CertifiedArtifact) -> frozenset[str]:
        """Return the household column names of a dataset artifact."""
        ...


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


def verify_region_data(
    catalog: NormalizedCatalog,
    inspector: CertifiedDataInspector,
    *,
    countries: Sequence[str],
) -> None:
    """Check the regions of the named countries against their certified artifacts.

    Each artifact is read at most once.
    """
    for country_id in countries:
        country = catalog.country(country_id)
        artifacts = {
            artifact.name: artifact for artifact in country.certified_artifacts
        }
        _verify_row_filters(country, artifacts, inspector)
