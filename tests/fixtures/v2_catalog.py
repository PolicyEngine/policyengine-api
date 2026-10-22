"""Deterministic PolicyEngine.py-like source objects for v2 catalog tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.extraction import extract_catalog
from policyengine_api.data.v2.catalog.region_references import RegionReference

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.records import NormalizedCatalog

POLICYENGINE_VERSION = "5.0.4"
DEPENDENCY_VERSIONS = {
    "policyengine-core": "3.30.1",
    "policyengine-us": "1.764.6",
    "policyengine-uk": "2.90.2",
}


def region_references() -> dict[str, tuple[RegionReference, ...]]:
    """Return small US and UK reference files.

    The US place has no filter rule, so publication leaves it out.
    """
    return {
        "us": (
            RegionReference(
                code="us",
                label="United States",
                region_type="national",
                parent_code=None,
                state_code=None,
                state_name=None,
                filter_value=None,
                v1_code="us",
            ),
            RegionReference(
                code="state/ca",
                label="California",
                region_type="state",
                parent_code="us",
                state_code="CA",
                state_name="California",
                filter_value="6",
                v1_code="state/ca",
            ),
            RegionReference(
                code="congressional_district/CA-01",
                label="California's 1st congressional district",
                region_type="congressional_district",
                parent_code="state/ca",
                state_code="CA",
                state_name="California",
                filter_value="601",
                v1_code="congressional_district/CA-01",
            ),
            RegionReference(
                code="place/CA-44000",
                label="Los Angeles",
                region_type="place",
                parent_code="state/ca",
                state_code="CA",
                state_name="California",
                filter_value=None,
                v1_code="place/CA-44000",
            ),
        ),
        "uk": (
            RegionReference(
                code="uk",
                label="United Kingdom",
                region_type="national",
                parent_code=None,
                state_code=None,
                state_name=None,
                filter_value=None,
                v1_code="uk",
            ),
            RegionReference(
                code="country/england",
                label="England",
                region_type="country",
                parent_code="uk",
                state_code=None,
                state_name=None,
                filter_value='["NORTH_EAST","LONDON"]',
                v1_code="country/england",
            ),
            RegionReference(
                code="constituency/E14001063",
                label="Aldershot",
                region_type="constituency",
                parent_code="country/england",
                state_code=None,
                state_name=None,
                filter_value="E14001063",
                v1_code="constituency/Aldershot",
            ),
            RegionReference(
                code="country/northern_ireland",
                label="Northern Ireland",
                region_type="country",
                parent_code="uk",
                state_code=None,
                state_name=None,
                filter_value="NORTHERN_IRELAND",
                v1_code="country/ni",
            ),
            RegionReference(
                code="local_authority/N09000011",
                label="Ards and North Down",
                region_type="local_authority",
                parent_code="country/northern_ireland",
                state_code=None,
                state_name=None,
                filter_value="N09000011",
                v1_code="local_authority/Ards and North Down",
            ),
        ),
    }


def _certified_artifact(path: str, *, revision: str = "fixture") -> SimpleNamespace:
    return SimpleNamespace(
        path=path,
        revision=revision,
        sha256="0" * 64,
        repo_id=None,
        repo_type=None,
    )


def _release_contents(country_id: str) -> tuple[dict, dict, SimpleNamespace]:
    """Return a country's certified datasets, region datasets and data package."""
    if country_id == "us":
        datasets = {
            "populace_us_2024": _certified_artifact("populace_us_2024.h5"),
            "populace_us_2024_acs_local": _certified_artifact(
                "populace_us_2024_acs_local.h5"
            ),
        }
        region_datasets = {
            "national": SimpleNamespace(path_template="populace_us_2024.h5"),
            "state": SimpleNamespace(path_template="populace_us_2024_acs_local.h5"),
            "congressional_district": SimpleNamespace(
                path_template="populace_us_2024_acs_local.h5"
            ),
        }
        data_package = SimpleNamespace(
            repo_id="policyengine/populace-us",
            repo_type="dataset",
            version="0.1.0",
            release_manifest_revision="fixture",
        )
        return datasets, region_datasets, data_package
    datasets = {
        "microcosm_uk_2024_25": _certified_artifact("microcosm_uk_2024_25.h5"),
        "microcosm_uk_2024_25_dense": _certified_artifact(
            "microcosm_uk_2024_25_dense.h5"
        ),
    }
    # As in PolicyEngine.py 6.10.0, constituencies and local authorities are
    # routed to the local-area dataset, which carries their codes.
    region_datasets = {
        "national": SimpleNamespace(path_template="microcosm_uk_2024_25.h5"),
        "constituency": SimpleNamespace(path_template="microcosm_uk_2024_25_dense.h5"),
        "local_authority": SimpleNamespace(
            path_template="microcosm_uk_2024_25_dense.h5"
        ),
    }
    data_package = SimpleNamespace(
        repo_id="example-org/example-uk-data",
        repo_type="model",
        version="1.0.0",
        release_manifest_revision="fixture",
    )
    return datasets, region_datasets, data_package


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
) -> SimpleNamespace:
    model_name = f"policyengine-{country_id}"
    default_dataset = {
        "us": "populace_us_2024",
        "uk": "microcosm_uk_2024_25",
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
        is_input_variable=True,
        hidden_input=False,
        module_name="household.income.employment_income",
        adds_parameter_path=None,
        subtracts_parameter_path=None,
        enum_values=None,
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
        economy=True,
        household=False,
        parameter_values=[
            SimpleNamespace(
                value=0.1,
                start_date=datetime(2025, 1, 1, tzinfo=UTC),
                end_date=datetime(2025, 12, 31, tzinfo=UTC),
            ),
            SimpleNamespace(
                value=0.2,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
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
    datasets, region_datasets, data_package = _release_contents(country_id)
    version_holder.release_manifest = SimpleNamespace(
        country_id=country_id,
        policyengine_version=policyengine_version,
        default_dataset=default_dataset,
        default_dataset_uri=default_uri,
        datasets=datasets,
        region_datasets=region_datasets,
        data_package=data_package,
    )
    version_holder.entities = [
        SimpleNamespace(key="person", plural="people", is_person=True),
        SimpleNamespace(key="household", plural="households", is_person=False),
    ]
    version_holder.basic_inputs = ["employment_income"]
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
    return {
        country_id: _model_source(
            country_id=country_id,
            country_package_version=DEPENDENCY_VERSIONS[f"policyengine-{country_id}"],
            policyengine_version=policyengine_version,
        )
        for country_id in ("us", "uk")
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
        region_references=region_references(),
    )


def add_enum_and_parameter_part_records(model: SimpleNamespace) -> None:
    """Add an enum variable and a variable whose parts are named by parameters.

    The enum's labels are a string and an integer. The two parameters hold the
    lists ``countable_income`` adds and subtracts.
    """
    for name in ("gov.example.countable_income", "gov.example.deductions"):
        parameter = SimpleNamespace(
            name=name,
            label=None,
            description=None,
            data_type=list,
            unit=None,
            economy=True,
            household=True,
            parameter_values=[
                SimpleNamespace(
                    value=["employment_income"],
                    start_date=datetime(2025, 1, 1, tzinfo=UTC),
                    end_date=None,
                )
            ],
        )
        model.parameters.append(parameter)
        model.parameters_by_name[name] = parameter
    variables = (
        SimpleNamespace(
            name="filing_status",
            label="Filing status",
            entity="person",
            description=None,
            data_type="Enum",
            possible_values=["SINGLE", "JOINT"],
            default_value="SINGLE",
            adds=None,
            subtracts=None,
            is_input_variable=True,
            hidden_input=False,
            module_name="household.demographic.filing_status",
            adds_parameter_path=None,
            subtracts_parameter_path=None,
            enum_values=[
                SimpleNamespace(value="SINGLE", label="Single"),
                SimpleNamespace(value="JOINT", label=2),
            ],
        ),
        SimpleNamespace(
            name="countable_income",
            label="Countable income",
            entity="person",
            description=None,
            data_type=float,
            possible_values=None,
            default_value=0.0,
            adds=["employment_income"],
            subtracts=["employment_income"],
            is_input_variable=False,
            hidden_input=False,
            module_name="household.income.countable_income",
            adds_parameter_path="gov.example.countable_income",
            subtracts_parameter_path="gov.example.deductions",
            enum_values=None,
        ),
    )
    for variable in variables:
        model.variables.append(variable)
        model.variables_by_name[variable.name] = variable
