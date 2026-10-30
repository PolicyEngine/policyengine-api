"""Normalize the installed PolicyEngine.py public model catalog."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import metadata as importlib_metadata
from typing import Any

from policyengine_api.data.v2.catalog.extraction_regions import (
    DATASET_YEAR_PATTERN,
    MAX_REGION_FILTER_VALUE_LENGTH,
    REVIEWED_DEFAULT_DATASETS,
    SUPPORTED_REGION_TYPES,
    dataset_year,
    normalize_region,
    select_region_datasets,
    verified_default_dataset,
    verified_source_regions,
)
from policyengine_api.data.v2.catalog.extraction_values import (
    JSON_VALUE_NORMALIZERS,
    CatalogExtractionError,
    catalog_identifier,
    normalize_json_value,
    optional_text,
    required_text,
)
from policyengine_api.data.v2.catalog.extraction_variables_and_parameters import (
    normalize_parameter,
    normalize_parameter_nodes,
    normalize_variable,
    public_named_records,
)
from policyengine_api.data.v2.catalog.records import (
    CountryCatalog,
    DatasetRecord,
    FallbackSummary,
    ModelRecord,
    ModelVersionRecord,
    NormalizedCatalog,
)
from policyengine_api.supported_countries import SUPPORTED_COUNTRY_IDS

__all__ = [
    "CURRENT_LAW_IDS",
    "DATASET_YEAR_PATTERN",
    "JSON_VALUE_NORMALIZERS",
    "MAX_REGION_FILTER_VALUE_LENGTH",
    "METADATA_TIME_PERIODS",
    "PLACEHOLDER_VERSIONS",
    "REQUIRED_DEPENDENCIES",
    "REVIEWED_DEFAULT_DATASETS",
    "SUPPORTED_COUNTRIES",
    "SUPPORTED_REGION_TYPES",
    "CatalogExtractionError",
    "extract_catalog",
    "extract_installed_catalog",
    "normalize_json_value",
]


SUPPORTED_COUNTRIES = SUPPORTED_COUNTRY_IDS
REQUIRED_DEPENDENCIES = (
    "policyengine-core",
    *(f"policyengine-{country_id}" for country_id in SUPPORTED_COUNTRY_IDS),
)
CURRENT_LAW_IDS = {"us": 2, "uk": 1}
METADATA_TIME_PERIODS = {
    "us": tuple(range(2035, 2021, -1)),
    "uk": tuple(range(2024, 2031)),
}
PLACEHOLDER_VERSIONS = frozenset({"", "0", "0.0", "0.0.0", "unknown"})


def _verify_bundle(
    *,
    bundle: Mapping[str, Any],
    policyengine_version: str,
    installed_version: Callable[[str], str],
) -> tuple[tuple[str, str], ...]:
    if (
        not isinstance(policyengine_version, str)
        or policyengine_version.strip().lower() in PLACEHOLDER_VERSIONS
    ):
        msg = "PolicyEngine.py version is a placeholder"
        raise CatalogExtractionError(msg)
    canonical_version = required_text(
        policyengine_version,
        field_name="PolicyEngine.py version",
        maximum=128,
    )
    manifest_version = bundle.get("policyengine_version") or bundle.get(
        "bundle_version"
    )
    if manifest_version != canonical_version:
        msg = "installed PolicyEngine.py version does not match its packaged manifest"
        raise CatalogExtractionError(msg)

    packages = bundle.get("packages")
    if not isinstance(packages, Mapping):
        msg = "PolicyEngine.py manifest has no package map"
        raise CatalogExtractionError(msg)

    observed_dependencies: list[tuple[str, str]] = []
    for package_name in REQUIRED_DEPENDENCIES:
        package = packages.get(package_name)
        if not isinstance(package, Mapping):
            msg = f"PolicyEngine.py manifest omits {package_name}"
            raise CatalogExtractionError(msg)
        expected = package.get("version")
        if not isinstance(expected, str) or expected.lower() in PLACEHOLDER_VERSIONS:
            msg = f"PolicyEngine.py manifest has no valid {package_name} version"
            raise CatalogExtractionError(msg)
        try:
            observed = installed_version(package_name)
        except importlib_metadata.PackageNotFoundError as error:
            msg = f"required installed distribution {package_name} is absent"
            raise CatalogExtractionError(msg) from error
        if observed != expected:
            msg = (
                f"installed {package_name} version does not match "
                "the PolicyEngine.py manifest"
            )
            raise CatalogExtractionError(msg)
        observed_dependencies.append((package_name, expected))
    return tuple(observed_dependencies)


def _verified_model_name(country_id: str, source_model: object) -> str:
    """Return the public model's name once it matches the country's model."""
    expected_model_name = f"policyengine-{country_id}"
    model_name = required_text(
        getattr(source_model, "id", None),
        field_name=f"{country_id} model name",
        maximum=32,
    )
    if model_name != expected_model_name:
        msg = f"{country_id} public model identity does not match {expected_model_name}"
        raise CatalogExtractionError(msg)
    return model_name


def _verified_release_manifest(
    country_id: str,
    source: object,
    *,
    policyengine_version: str,
    expected_country_package_version: str,
) -> object:
    """Return the public model's release manifest once its package and manifest match.

    The model package must be the country's at the bundle's version, and the
    manifest must name the country and the installed PolicyEngine.py version.
    """
    expected_model_name = f"policyengine-{country_id}"
    model_package = getattr(source, "model_package", None)
    if getattr(model_package, "name", None) != expected_model_name:
        msg = (
            f"{country_id} public model package identity does not match "
            f"{expected_model_name}"
        )
        raise CatalogExtractionError(msg)
    if getattr(model_package, "version", None) != expected_country_package_version:
        msg = f"{country_id} public model does not match the PolicyEngine.py manifest"
        raise CatalogExtractionError(msg)
    release_manifest = getattr(source, "release_manifest", None)
    if getattr(release_manifest, "country_id", None) != country_id:
        msg = f"{country_id} public model has an inconsistent release manifest"
        raise CatalogExtractionError(msg)
    if getattr(release_manifest, "policyengine_version", None) != policyengine_version:
        msg = (
            f"{country_id} public model was not certified by the installed "
            "PolicyEngine.py version"
        )
        raise CatalogExtractionError(msg)
    return release_manifest


def _normalize_country(
    *,
    country_id: str,
    source: object,
    policyengine_version: str,
    expected_country_package_version: str,
) -> CountryCatalog:
    source_model = getattr(source, "model", None)
    model_name = _verified_model_name(country_id, source_model)
    model_id = catalog_identifier("model", model_name)
    model_version_id = catalog_identifier(
        "model-version", model_id, policyengine_version
    )
    release_manifest = _verified_release_manifest(
        country_id,
        source,
        policyengine_version=policyengine_version,
        expected_country_package_version=expected_country_package_version,
    )

    variables = tuple(
        normalize_variable(variable, model_version_id=model_version_id)
        for variable in public_named_records(
            source,
            attribute="variables_by_name",
            entity_name="variable",
        )
    )
    parameter_nodes = normalize_parameter_nodes(
        source, model_version_id=model_version_id
    )
    parameters = tuple(
        normalize_parameter(parameter, model_version_id=model_version_id)
        for parameter in public_named_records(
            source,
            attribute="parameters_by_name",
            entity_name="parameter",
        )
    )

    reviewed_default, default_dataset_uri = verified_default_dataset(
        country_id, release_manifest
    )
    source_regions = verified_source_regions(country_id, source)
    dataset_selection = select_region_datasets(
        country_id,
        source_regions,
        reviewed_default=reviewed_default,
        default_dataset_uri=default_dataset_uri,
    )

    datasets = tuple(
        DatasetRecord(
            id=catalog_identifier("dataset", model_version_id, name),
            model_version_id=model_version_id,
            name=name,
            description=f"PolicyEngine.py logical input dataset {name}",
            year=dataset_year(name),
        )
        for name in sorted(dataset_selection.dataset_names)
    )
    dataset_ids = {dataset.name: dataset.id for dataset in datasets}
    region_dataset_ids = {
        code: dataset_ids[name]
        for code, name in dataset_selection.region_dataset_names.items()
    }
    regions = [
        normalize_region(
            source_region,
            model_version_id=model_version_id,
            region_dataset_ids=region_dataset_ids,
        )
        for source_region in source_regions
    ]

    return CountryCatalog(
        country_id=country_id,
        model=ModelRecord(
            id=model_id,
            country_id=country_id,
            name=model_name,
            description=optional_text(
                getattr(source_model, "description", None),
                field_name=f"{country_id} model description",
            ),
        ),
        model_version=ModelVersionRecord(
            id=model_version_id,
            model_id=model_id,
            version=policyengine_version,
            description=optional_text(
                getattr(source_model, "description", None),
                field_name=f"{country_id} model-version description",
            ),
            current_law_id=CURRENT_LAW_IDS[country_id],
            metadata_time_periods=METADATA_TIME_PERIODS[country_id],
        ),
        variables=variables,
        parameter_nodes=parameter_nodes,
        parameters=parameters,
        datasets=datasets,
        regions=tuple(sorted(regions, key=lambda record: record.code)),
        fallback_summaries=tuple(
            FallbackSummary(region_type=region_type, count=count)
            for region_type, count in sorted(dataset_selection.fallback_counts.items())
        ),
    )


def extract_catalog(
    *,
    bundle: Mapping[str, Any],
    policyengine_version: str,
    models: Mapping[str, object],
    installed_version: Callable[[str], str] = importlib_metadata.version,
) -> NormalizedCatalog:
    """Validate and normalize supplied PolicyEngine.py public objects."""
    dependencies = _verify_bundle(
        bundle=bundle,
        policyengine_version=policyengine_version,
        installed_version=installed_version,
    )
    missing = [country for country in SUPPORTED_COUNTRIES if country not in models]
    if missing:
        msg = f"PolicyEngine.py public models are absent for: {', '.join(missing)}"
        raise CatalogExtractionError(msg)

    package_map = bundle["packages"]
    countries = tuple(
        _normalize_country(
            country_id=country_id,
            source=models[country_id],
            policyengine_version=policyengine_version,
            expected_country_package_version=package_map[f"policyengine-{country_id}"][
                "version"
            ],
        )
        for country_id in SUPPORTED_COUNTRIES
    )
    return NormalizedCatalog(
        policyengine_version=policyengine_version,
        dependency_versions=dependencies,
        countries=countries,
    )


def extract_installed_catalog() -> NormalizedCatalog:
    """Load and normalize the installed PolicyEngine.py certified catalog."""
    import policyengine
    from policyengine.bundle import (
        get_current_bundle,
    )

    policyengine_version = importlib_metadata.version("policyengine")
    return extract_catalog(
        bundle=get_current_bundle(),
        policyengine_version=policyengine_version,
        models={
            country_id: getattr(policyengine, country_id).model
            for country_id in SUPPORTED_COUNTRIES
        },
    )
