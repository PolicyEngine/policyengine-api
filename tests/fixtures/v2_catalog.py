"""Deterministic PolicyEngine.py-like source objects for v2 catalog tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from policyengine_api.data.v2.catalog.extraction import extract_catalog
from policyengine_api.data.v2.catalog.records import NormalizedCatalog


POLICYENGINE_VERSION = "5.0.4"
DEPENDENCY_VERSIONS = {
    "policyengine-core": "3.30.1",
    "policyengine-us": "1.764.6",
    "policyengine-uk": "2.90.2",
}


class RegionRegistry(list):
    """Small iterable with the public registry's country identifier."""

    def __init__(self, country_id: str, regions: list[SimpleNamespace]):
        super().__init__(regions)
        self.country_id = country_id


def _strategy(field: str, value: str | int) -> SimpleNamespace:
    return SimpleNamespace(
        strategy_type="row_filter",
        variable_name=field,
        variable_value=value,
        additional_filters={},
    )


def _region(
    *,
    code: str,
    label: str,
    region_type: str,
    parent_code: str | None = None,
    dataset_path: str | None = None,
    strategy: SimpleNamespace | None = None,
    state_code: str | None = None,
    state_name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        code=code,
        label=label,
        region_type=region_type,
        parent_code=parent_code,
        dataset_path=dataset_path,
        scoping_strategy=strategy,
        requires_filter=strategy is not None,
        state_code=state_code,
        state_name=state_name,
    )


def bundle(*, policyengine_version: str = POLICYENGINE_VERSION) -> dict:
    """Return a minimal packaged-bundle manifest."""

    return {
        "bundle_version": policyengine_version,
        "policyengine_version": policyengine_version,
        "packages": {
            "policyengine": {
                "name": "policyengine",
                "version": policyengine_version,
            },
            **{
                name: {"name": name, "version": version}
                for name, version in DEPENDENCY_VERSIONS.items()
            },
        },
    }


def _model_source(
    *,
    country_id: str,
    country_package_version: str,
    policyengine_version: str,
    regions: list[SimpleNamespace],
) -> SimpleNamespace:
    model_name = f"policyengine-{country_id}"
    default_dataset = {
        "us": "populace_us_2024",
        "uk": "enhanced_frs_2024_25",
    }[country_id]
    default_uri = f"hf://policyengine/{country_id}/{default_dataset}.h5@fixture"
    version_holder = SimpleNamespace()
    variable = SimpleNamespace(
        name="employment_income",
        label="Employment income",
        entity="person",
        description="Employment income before tax",
        data_type=float,
        possible_values=None,
        default_value=0.0,
        adds=None,
        subtracts=None,
    )
    parameter_node = SimpleNamespace(
        name="gov.example",
        label="Example policy",
        description="Example policy parameters",
    )
    parameter = SimpleNamespace(
        name="gov.example.rate",
        label="Example rate",
        description="An example rate",
        data_type=float,
        unit="/1",
        parameter_values=[
            SimpleNamespace(
                value=0.1,
                start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2025, 12, 31, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                value=0.2,
                start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end_date=None,
            ),
        ],
    )
    version_holder.model = SimpleNamespace(
        id=model_name,
        description=f"Fixture {country_id.upper()} model",
    )
    version_holder.version = country_package_version
    version_holder.model_package = SimpleNamespace(
        name=model_name,
        version=country_package_version,
    )
    version_holder.release_manifest = SimpleNamespace(
        country_id=country_id,
        policyengine_version=policyengine_version,
        default_dataset=default_dataset,
        default_dataset_uri=default_uri,
    )
    version_holder.region_registry = RegionRegistry(country_id, regions)
    version_holder.variables = [variable]
    version_holder.parameter_nodes = [parameter_node]
    version_holder.parameters = [parameter]
    version_holder.variables_by_name = {variable.name: variable}
    version_holder.parameter_nodes_by_name = {parameter_node.name: parameter_node}
    version_holder.parameters_by_name = {parameter.name: parameter}
    return version_holder


def source_models(
    *,
    policyengine_version: str = POLICYENGINE_VERSION,
) -> dict[str, SimpleNamespace]:
    """Return US and UK public-model fixtures."""

    us_default_uri = "hf://policyengine/us/populace_us_2024.h5@fixture"
    uk_default_uri = "hf://policyengine/uk/enhanced_frs_2024_25.h5@fixture"
    return {
        "us": _model_source(
            country_id="us",
            country_package_version=DEPENDENCY_VERSIONS["policyengine-us"],
            policyengine_version=policyengine_version,
            regions=[
                _region(
                    code="us",
                    label="United States",
                    region_type="national",
                    dataset_path=us_default_uri,
                ),
                _region(
                    code="state/ca",
                    label="California",
                    region_type="state",
                    parent_code="us",
                    dataset_path="hf://policyengine/us/populace_us_ca_2024.h5@fixture",
                    strategy=_strategy("state_fips", 6),
                    state_code="CA",
                    state_name="California",
                ),
                _region(
                    code="place/CA-44000",
                    label="Los Angeles",
                    region_type="place",
                    parent_code="state/ca",
                    state_code="CA",
                    state_name="California",
                ),
            ],
        ),
        "uk": _model_source(
            country_id="uk",
            country_package_version=DEPENDENCY_VERSIONS["policyengine-uk"],
            policyengine_version=policyengine_version,
            regions=[
                _region(
                    code="uk",
                    label="United Kingdom",
                    region_type="national",
                    dataset_path=uk_default_uri,
                ),
                _region(
                    code="country/england",
                    label="England",
                    region_type="country",
                    parent_code="uk",
                    strategy=_strategy("country", "ENGLAND"),
                ),
            ],
        ),
    }


def installed_version(name: str) -> str:
    """Return fixture observed versions."""

    return DEPENDENCY_VERSIONS[name]


def normalized_catalog(
    *,
    policyengine_version: str = POLICYENGINE_VERSION,
) -> NormalizedCatalog:
    """Return the complete deterministic normalized fixture."""

    return extract_catalog(
        bundle=bundle(policyengine_version=policyengine_version),
        policyengine_version=policyengine_version,
        models=source_models(policyengine_version=policyengine_version),
        installed_version=installed_version,
    )
