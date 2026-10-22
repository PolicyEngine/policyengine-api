"""UK constituencies and local authorities follow what the certified release provides.

A release with the constituency and local-authority weight matrices reweights
the national dataset's households. A release without them that routes each
region type to its own dataset selects that dataset's households by the
region's ONS code in a household column.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from policyengine_api.data.v2.catalog.extraction import (
    CatalogExtractionError,
    extract_catalog,
)
from policyengine_api.data.v2.catalog.region_data_verification import (
    RegionDataVerificationError,
    verify_region_data,
)
from policyengine_api.data.v2.catalog.region_references import RegionReference
from tests.fixtures.v2_catalog import (
    POLICYENGINE_VERSION,
    bundle,
    installed_version,
    region_references,
    source_models,
)

ROUTED_DATASET = "microcosm_uk_2024_25_dense"
MAIDSTONE = RegionReference(
    code="local_authority/E07000110",
    label="Maidstone",
    region_type="local_authority",
    parent_code="country/england",
    state_code=None,
    state_name=None,
    filter_value="E07000110",
    v1_code="local_authority/Maidstone",
)
WEIGHT_MATRICES = ("parliamentary_constituency_weights", "local_authority_weights")


def _references() -> dict[str, tuple[RegionReference, ...]]:
    references = region_references()
    return {**references, "uk": (*references["uk"], MAIDSTONE)}


def _route_to_region_dataset(models: dict[str, SimpleNamespace]) -> None:
    """Give the UK release a dense region dataset for both region types."""
    manifest = models["uk"].release_manifest
    manifest.datasets[ROUTED_DATASET] = SimpleNamespace(
        path=f"{ROUTED_DATASET}.h5",
        revision="fixture",
        sha256="0" * 64,
        repo_id=None,
        repo_type=None,
    )
    for region_type in ("constituency", "local_authority"):
        manifest.region_datasets[region_type] = SimpleNamespace(
            path_template=f"{ROUTED_DATASET}.h5"
        )


def _remove_weight_matrices(models: dict[str, SimpleNamespace]) -> None:
    for matrix_name in WEIGHT_MATRICES:
        models["uk"].release_manifest.datasets.pop(matrix_name, None)


def _uk_regions(models: dict[str, SimpleNamespace]):
    catalog = extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
        region_references=_references(),
    )
    uk = catalog.country("uk")
    dataset_names = {dataset.id: dataset.name for dataset in uk.datasets}
    scoped = {
        region.code: (
            dataset_names[region.default_dataset_id],
            region.filter_strategy,
            region.filter_field,
            region.filter_value,
        )
        for region in uk.regions
        if region.region_type in {"constituency", "local_authority"}
    }
    return catalog, scoped


def test_release_without_weight_matrices_row_filters_the_routed_dataset() -> None:
    models = source_models()
    _route_to_region_dataset(models)
    _remove_weight_matrices(models)

    catalog, scoped = _uk_regions(models)

    assert scoped == {
        "constituency/E14001063": (
            ROUTED_DATASET,
            "row_filter",
            "constituency_code_oa",
            "E14001063",
        ),
        "local_authority/E07000110": (
            ROUTED_DATASET,
            "row_filter",
            "la_code_oa",
            "E07000110",
        ),
    }
    assert [
        artifact.name for artifact in catalog.country("uk").certified_artifacts
    ] == [
        "enhanced_frs_2024_25",
        ROUTED_DATASET,
    ]


def test_release_with_weight_matrices_keeps_weight_replacement() -> None:
    models = source_models()
    models["uk"].release_manifest.datasets["local_authority_weights"] = SimpleNamespace(
        path="local_authority_weights.h5",
        revision="fixture",
        sha256="0" * 64,
        repo_id=None,
        repo_type=None,
    )
    _route_to_region_dataset(models)

    _catalog, scoped = _uk_regions(models)

    assert scoped == {
        "constituency/E14001063": (
            "enhanced_frs_2024_25",
            "weight_replacement",
            "parliamentary_constituency_weights",
            "E14001063",
        ),
        "local_authority/E07000110": (
            "enhanced_frs_2024_25",
            "weight_replacement",
            "local_authority_weights",
            "E07000110",
        ),
    }


def test_release_with_neither_weight_matrices_nor_a_region_dataset_fails() -> None:
    models = source_models()
    _remove_weight_matrices(models)

    with pytest.raises(
        CatalogExtractionError,
        match=r"^the uk release certifies neither the weight matrix "
        r"parliamentary_constituency_weights nor a constituency region dataset, so "
        r"region 'constituency/E14001063' cannot select its households$",
    ):
        _uk_regions(models)


class _ColumnsOnlyInspector:
    """Answers household columns from a fixed map and never reads weight matrices."""

    def __init__(self, columns: dict[str, frozenset[str]]) -> None:
        self.columns = columns

    def household_columns(self, artifact) -> frozenset[str]:
        return self.columns[artifact.name]

    def weight_matrix_row_count(self, artifact) -> int:
        msg = f"no weight matrix is read, but {artifact.name} was"
        raise AssertionError(msg)


def test_verification_requires_the_ons_code_columns_in_the_routed_dataset() -> None:
    models = source_models()
    _route_to_region_dataset(models)
    _remove_weight_matrices(models)
    catalog, _scoped = _uk_regions(models)
    columns = {
        "enhanced_frs_2024_25": frozenset({"region"}),
        ROUTED_DATASET: frozenset({"constituency_code_oa", "la_code_oa"}),
    }

    verify_region_data(catalog, _ColumnsOnlyInspector(columns), countries=("uk",))

    columns[ROUTED_DATASET] = frozenset({"constituency_code_oa"})
    with pytest.raises(
        RegionDataVerificationError,
        match=rf"^the certified dataset {ROUTED_DATASET} has no household column "
        r"la_code_oa, which 1 uk region filters on \(local_authority/E07000110\)$",
    ):
        verify_region_data(catalog, _ColumnsOnlyInspector(columns), countries=("uk",))
