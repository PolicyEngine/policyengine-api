"""Pin the catalog extractor's error for each inconsistent public-model shape."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from policyengine_api.data.v2.catalog.extraction import (
    CatalogExtractionError,
    extract_catalog,
    normalize_json_value,
)
from tests.fixtures.v2_catalog import (
    POLICYENGINE_VERSION,
    bundle,
    installed_version,
    source_models,
)

if TYPE_CHECKING:
    from types import SimpleNamespace


def _extract(models: dict[str, SimpleNamespace]) -> None:
    extract_catalog(
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


def _remove_region_registry(models: dict[str, SimpleNamespace]) -> None:
    models["us"].region_registry = None


def _mislabel_region_registry(models: dict[str, SimpleNamespace]) -> None:
    models["us"].region_registry.country_id = "uk"


def _duplicate_region_codes(models: dict[str, SimpleNamespace]) -> None:
    registry = models["us"].region_registry
    registry.append(registry[1])


def _remove_national_region(models: dict[str, SimpleNamespace]) -> None:
    registry = models["us"].region_registry
    del registry[0]


def _give_national_region_another_dataset(models: dict[str, SimpleNamespace]) -> None:
    models["uk"].region_registry[0].dataset_path = "hf://policyengine/uk/other.h5"


def _give_filter_an_unsupported_value(models: dict[str, SimpleNamespace]) -> None:
    models["us"].region_registry[1].scoping_strategy.variable_value = {"state": "CA"}


def _give_filter_additional_filters(models: dict[str, SimpleNamespace]) -> None:
    models["uk"].region_registry[1].scoping_strategy.additional_filters = {
        "region": "LONDON"
    }


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
        (_remove_region_registry, "^us public region registry is absent$"),
        (_mislabel_region_registry, "^us public region registry is absent$"),
        (
            _duplicate_region_codes,
            r"^duplicate region natural keys: \['state/ca'\]$",
        ),
        (_remove_national_region, "^us national region is absent$"),
        (
            _give_national_region_another_dataset,
            "^uk national region does not use the reviewed dataset$",
        ),
        (
            _give_filter_an_unsupported_value,
            "^region 'state/ca' has an unsupported filter value$",
        ),
        (
            _give_filter_additional_filters,
            "^region 'country/england' has unsupported additional filters$",
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


def test_national_region_without_a_dataset_path_uses_the_reviewed_dataset() -> None:
    models = source_models()
    models["us"].region_registry[0].dataset_path = None

    extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )


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
