"""Pin the catalog extractor's error for each inconsistent public-model shape."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from enum import Enum
from types import SimpleNamespace

import pytest

from policyengine_api.data.v2.catalog.extraction import (
    CatalogExtractionError,
    extract_catalog,
    normalize_json_value,
)
from policyengine_api.data.v2.catalog.region_references import RegionReference
from tests.fixtures.v2_catalog import (
    POLICYENGINE_VERSION,
    bundle,
    installed_version,
    region_references,
    source_models,
)


def _extract(models: dict[str, SimpleNamespace]) -> None:
    extract_catalog(
        region_references=region_references(),
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )


def _break_package_version(models: dict[str, SimpleNamespace]) -> None:
    models["us"].model_package.version = "0.0.1"


def _break_manifest_country(models: dict[str, SimpleNamespace]) -> None:
    models["us"].release_manifest.country_id = "uk"


def _break_manifest_version(models: dict[str, SimpleNamespace]) -> None:
    models["us"].release_manifest.policyengine_version = "9.9.9"


@pytest.mark.parametrize(
    ("break_models", "message"),
    [
        (
            _break_package_version,
            "^us public model does not match the PolicyEngine.py manifest$",
        ),
        (
            _break_manifest_country,
            "^us public model has an inconsistent release manifest$",
        ),
        (
            _break_manifest_version,
            "^us public model was not certified by the installed PolicyEngine.py "
            "version$",
        ),
    ],
)
def test_inconsistent_public_models_fail_with_a_specific_message(
    break_models,
    message: str,
) -> None:
    models = source_models()
    break_models(models)

    with pytest.raises(CatalogExtractionError, match=message):
        _extract(models)


References = dict[str, tuple[RegionReference, ...]]


def _replace_reference(
    references: References, country_id: str, code: str, **changes: str | None
) -> None:
    references[country_id] = tuple(
        replace(reference, **changes) if reference.code == code else reference
        for reference in references[country_id]
    )


def _point_national_region_at_another_dataset(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    models["uk"].release_manifest.region_datasets[
        "national"
    ].path_template = "frs_2024_25.h5"
    models["uk"].release_manifest.datasets["frs_2024_25"] = SimpleNamespace(
        path="frs_2024_25.h5", revision="fixture", repo_id=None, repo_type=None
    )


def _name_an_uncertified_region_dataset(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    models["us"].release_manifest.region_datasets["state"].path_template = "missing.h5"


def _name_a_per_region_dataset_template(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    models["us"].release_manifest.region_datasets[
        "state"
    ].path_template = "populace_{state_code}.h5"


def _stop_routing_constituencies(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    del models["uk"].release_manifest.region_datasets["constituency"]


def _stop_routing_local_authorities(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    del models["uk"].release_manifest.region_datasets["local_authority"]


def _drop_a_filter_value(
    _models: dict[str, SimpleNamespace], references: References
) -> None:
    _replace_reference(references, "us", "state/ca", filter_value=None)


def _give_the_national_region_a_filter_value(
    _models: dict[str, SimpleNamespace], references: References
) -> None:
    _replace_reference(references, "us", "us", filter_value="0")


def _place_a_district_under_a_place(
    _models: dict[str, SimpleNamespace], references: References
) -> None:
    _replace_reference(
        references,
        "us",
        "congressional_district/CA-01",
        parent_code="place/CA-44000",
    )


def _remove_a_country_from_the_references(
    _models: dict[str, SimpleNamespace], references: References
) -> None:
    del references["uk"]


def _remove_the_dataset_map(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    models["us"].release_manifest.datasets = None


def _remove_the_reviewed_default_dataset(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    del models["us"].release_manifest.datasets["populace_us_2024"]


def _remove_the_region_dataset_map(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    models["us"].release_manifest.region_datasets = None


def _remove_a_region_dataset_path(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    models["us"].release_manifest.region_datasets["state"].path_template = None


def _remove_an_artifact_path(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    models["us"].release_manifest.datasets["populace_us_2024"].path = None


def _remove_every_artifact_revision(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    manifest = models["us"].release_manifest
    manifest.datasets["populace_us_2024"].revision = None
    manifest.data_package.release_manifest_revision = None
    manifest.data_package.version = None


def _drop_the_region_dataset_attribute(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    del models["us"].release_manifest.region_datasets


def _remove_every_artifact_repository(
    models: dict[str, SimpleNamespace], _references: References
) -> None:
    models["us"].release_manifest.data_package.repo_id = None


@pytest.mark.parametrize(
    ("break_sources", "message"),
    [
        (_remove_the_dataset_map, "^us release manifest has no dataset map$"),
        (
            _drop_the_region_dataset_attribute,
            "^us release manifest lacks datasets, region_datasets or data_package$",
        ),
        (
            _remove_the_reviewed_default_dataset,
            "^us release does not certify populace_us_2024$",
        ),
        (
            _remove_the_region_dataset_map,
            "^us release manifest has no region dataset map$",
        ),
        (
            _remove_a_region_dataset_path,
            "^us state region dataset must be a non-empty string$",
        ),
        (
            _remove_an_artifact_path,
            "^us release artifact populace_us_2024 path must be a non-empty string$",
        ),
        (
            _remove_every_artifact_revision,
            "^us release artifact populace_us_2024 revision must be a non-empty "
            "string$",
        ),
        (
            _remove_every_artifact_repository,
            "^us release artifact populace_us_2024 repository must be a non-empty "
            "string$",
        ),
        (
            _point_national_region_at_another_dataset,
            "^uk national region does not use the reviewed dataset$",
        ),
        (
            _name_an_uncertified_region_dataset,
            "^us release names no certified dataset at path 'missing.h5' for state "
            "regions$",
        ),
        (
            _name_a_per_region_dataset_template,
            r"^us state regions name a per-region dataset template "
            r"'populace_\{state_code\}.h5', which the catalog does not support$",
        ),
        (
            _stop_routing_constituencies,
            "^the uk release routes no dataset to constituency regions, so region "
            "'constituency/E14001063' cannot select its households$",
        ),
        (
            _stop_routing_local_authorities,
            "^the uk release routes no dataset to local_authority regions, so region "
            "'local_authority/N09000011' cannot select its households$",
        ),
        (_drop_a_filter_value, "^region 'state/ca' has no filter value$"),
        (
            _give_the_national_region_a_filter_value,
            "^region 'us' has a filter value, but a national region selects every "
            "household$",
        ),
        (
            _place_a_district_under_a_place,
            "^region 'congressional_district/CA-01' cannot be published because its "
            "parent 'place/CA-44000' is left out$",
        ),
        (
            _remove_a_country_from_the_references,
            "^region references are absent for: uk$",
        ),
    ],
)
def test_inconsistent_regions_fail_with_a_specific_message(
    break_sources,
    message: str,
) -> None:
    models = source_models()
    references = region_references()
    break_sources(models, references)

    with pytest.raises(CatalogExtractionError, match=message):
        extract_catalog(
            region_references=references,
            bundle=bundle(),
            policyengine_version=POLICYENGINE_VERSION,
            models=models,
            installed_version=installed_version,
        )


def test_national_region_without_a_release_dataset_uses_the_reviewed_dataset() -> None:
    models = source_models()
    del models["us"].release_manifest.region_datasets["national"]

    catalog = extract_catalog(
        region_references=region_references(),
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )

    us = catalog.country("us")
    national = next(region for region in us.regions if region.code == "us")
    datasets = {dataset.id: dataset.name for dataset in us.datasets}
    assert datasets[national.default_dataset_id] == "populace_us_2024"
    assert us.fallback_summaries == ()


class _ScalarWrapper:
    """A numpy-like scalar whose item() returns a plain Python value."""

    def __init__(self, scalar: object) -> None:
        self._scalar = scalar

    def item(self) -> object:
        return self._scalar


class _SelfReturningScalar:
    """An object whose item() returns itself, so it never becomes a scalar."""

    def item(self) -> object:
        return self


def test_normalize_json_value_rejects_nan_and_keeps_infinities_as_strings() -> None:
    with pytest.raises(CatalogExtractionError, match=r"^NaN is not JSON-compatible$"):
        normalize_json_value(math.nan)

    assert normalize_json_value(math.inf) == "Infinity"
    assert normalize_json_value(-math.inf) == "-Infinity"


def test_normalize_json_value_unwraps_scalars_and_rejects_self_returning_items() -> (
    None
):
    assert normalize_json_value(_ScalarWrapper(3)) == 3
    assert normalize_json_value((1, [2, (3,)])) == [1, [2, [3]]]
    with pytest.raises(
        CatalogExtractionError,
        match=r"^unsupported JSON value type .*_SelfReturningScalar$",
    ):
        normalize_json_value(_SelfReturningScalar())
    with pytest.raises(
        CatalogExtractionError, match=r"^JSON object keys must be strings$"
    ):
        normalize_json_value({1: "one"})


class _Colour(Enum):
    RED = "red"


class _Pair(tuple, Enum):
    __slots__ = ()

    FIRST = (1, 2)


class _Date(date, Enum):
    LAUNCH = (2024, 1, 2)


def test_normalize_json_value_reads_enums_by_value_before_their_base_type() -> None:
    assert normalize_json_value(_Colour.RED) == "red"
    assert normalize_json_value(_Pair.FIRST) == [1, 2]
    assert normalize_json_value(_Date.LAUNCH) == "2024-01-02"
    assert normalize_json_value({"colour": [_Colour.RED]}) == {"colour": ["red"]}
