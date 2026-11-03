"""A typed fake metadata reader and a client that serves v2 metadata routes from it."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from flask import Flask, jsonify

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.metadata.types import (
    MetadataCanonicalParameterValue,
    MetadataCatalogParameter,
    MetadataCatalogParametersResult,
    MetadataCatalogVariablesResult,
    MetadataDataset,
    MetadataDatasetOption,
    MetadataDatedValue,
    MetadataDetailResult,
    MetadataEconomyOptions,
    MetadataEconomyOptionsResult,
    MetadataEntity,
    MetadataModel,
    MetadataModelCatalogResult,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataRegionOption,
    MetadataTimePeriodOption,
    MetadataVariable,
)


class ResourceReader:
    def __init__(
        self,
        results: dict[str, object],
        *,
        error: Exception | None = None,
        close_error: Exception | None = None,
    ):
        self.results = results
        self.error = error
        self.close_error = close_error
        self.calls: list[tuple[str, tuple, dict]] = []
        self.closed = False

    def __getattr__(self, name: str):
        if name not in self.results:
            raise AttributeError(name)

        def read(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if self.error is not None:
                raise self.error
            return self.results[name]

        return read

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def resource_results() -> tuple[dict[str, object], dict[str, object]]:
    version = "4.20.3"
    model_id = uuid4()
    model_version_id = uuid4()
    variable_id = uuid4()
    parameter_id = uuid4()
    parameter_value_id = uuid4()
    dataset_id = uuid4()
    region_id = uuid4()
    model = MetadataModel(
        id=model_id,
        name="policyengine-us",
        description="US model",
    )
    model_version = MetadataModelVersionDetail(
        id=model_version_id,
        model_id=model_id,
        version=version,
        description="PolicyEngine.py catalog",
        current_law_id=2,
        metadata_time_periods=[2026],
    )
    variable = MetadataVariable(
        id=variable_id,
        name="employment_income",
        label="Employment income",
        entity="person",
        description=None,
        data_type="float",
        possible_values=None,
        default_value=0,
        adds=None,
        subtracts=None,
        is_input_variable=True,
        hidden_input=False,
        module_name=None,
        adds_parameter_path=None,
        subtracts_parameter_path=None,
        enum_values=None,
        unit="currency-USD",
        definition_period="year",
    )
    parameter = MetadataParameterSummary(
        id=parameter_id,
        name="gov.example.rate",
        label="Rate",
        description=None,
        data_type="float",
        unit="/1",
        economy=True,
        household=False,
    )
    parameter_value = MetadataCanonicalParameterValue(
        id=parameter_value_id,
        parameter_id=parameter_id,
        value=0.1,
        start_date=datetime(2025, 1, 1, tzinfo=UTC),
        end_date=None,
    )
    dataset = MetadataDataset(
        id=dataset_id,
        name="populace_us_2024",
        description="National input dataset",
        year=2024,
    )
    region = MetadataRegion(
        id=region_id,
        code="us",
        label="United States",
        region_type="national",
        requires_filter=False,
        filter_field=None,
        filter_value=None,
        filter_strategy=None,
        parent_code=None,
        state_code=None,
        state_name=None,
        default_dataset_id=dataset_id,
    )

    def page(items: list[object]) -> MetadataPageResult:
        return MetadataPageResult(
            policyengine_version=version,
            items=items,
            offset=0,
            limit=100,
            has_more=False,
        )

    def detail(item: object) -> MetadataDetailResult:
        return MetadataDetailResult(policyengine_version=version, item=item)

    return (
        {
            "list_models": page([model]),
            "get_model": detail(model),
            "get_model_by_country": MetadataModelSelectionResult(
                policyengine_version=version,
                model=model,
                model_version=model_version,
            ),
            "list_model_versions": page([model_version]),
            "get_model_version": detail(model_version),
            "list_variables": page([variable]),
            "get_variable": detail(variable),
            "list_parameters": page([parameter]),
            "list_parameter_children": page(
                [
                    MetadataParameterChild(
                        path=parameter.name,
                        label=parameter.label or parameter.name,
                        type="parameter",
                        parameter=parameter,
                    )
                ]
            ),
            "get_parameter": detail(parameter),
            "list_parameter_values": page([parameter_value]),
            "get_parameter_value": detail(parameter_value),
            "list_datasets": page([dataset]),
            "get_dataset": detail(dataset),
            "list_regions": page([region]),
            "get_region_by_code": detail(region),
            "get_region": detail(region),
            "get_catalog_parameters": MetadataCatalogParametersResult(
                policyengine_version=version,
                catalog_format=2,
                parameters=[
                    MetadataCatalogParameter(
                        **parameter.model_dump(),
                        values=[
                            MetadataDatedValue(
                                start_date=datetime(2025, 1, 1, tzinfo=UTC),
                                end_date=None,
                                value=0.1,
                            )
                        ],
                    )
                ],
                node_labels={"gov.example": "Example policy"},
                missing_names=["gov.removed"],
            ),
            "get_catalog_variables": MetadataCatalogVariablesResult(
                policyengine_version=version,
                catalog_format=2,
                variables=[variable],
                part_parameter_values={
                    "gov.example.parts": [
                        MetadataDatedValue(
                            start_date=datetime(2025, 1, 1, tzinfo=UTC),
                            end_date=None,
                            value=["employment_income"],
                        )
                    ]
                },
            ),
            "get_model_catalog": MetadataModelCatalogResult(
                policyengine_version=version,
                catalog_format=2,
                model=model,
                model_version=model_version,
                entities=[
                    MetadataEntity(key="person", plural="people", is_person=True)
                ],
                basic_inputs=["employment_income"],
                regions=[region],
                datasets=[dataset],
                economy_options=MetadataEconomyOptions(
                    region=[
                        MetadataRegionOption(
                            name="us", label="United States", type="national"
                        )
                    ],
                    time_period=[MetadataTimePeriodOption(name=2026, label="2026")],
                    datasets=[
                        MetadataDatasetOption(
                            name="populace_us_2024", label="Microcosm"
                        )
                    ],
                ),
            ),
            "get_economy_options": MetadataEconomyOptionsResult(
                policyengine_version=version,
                current_law_id=2,
                region=[
                    MetadataRegionOption(
                        name="us",
                        label="United States",
                        type="national",
                    )
                ],
                time_period=[MetadataTimePeriodOption(name=2026, label="2026")],
                datasets=[
                    MetadataDatasetOption(name="populace_us_2024", label="Microcosm")
                ],
            ),
        },
        {
            "model_id": model_id,
            "model_version_id": model_version_id,
            "variable_id": variable_id,
            "parameter_id": parameter_id,
            "parameter_value_id": parameter_value_id,
            "dataset_id": dataset_id,
            "region_id": region_id,
        },
    )


def metadata_route_client(factory, *, response_cache=None) -> TestClient:
    flask_app = Flask(__name__)

    @flask_app.get("/<country_id>/metadata")
    def v1_metadata(country_id: str):
        return jsonify(
            {
                "status": "ok",
                "message": None,
                "result": {"source": "v1", "country_id": country_id},
            }
        )

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_metadata_reader_factory=factory,
        v2_metadata_response_cache=response_cache,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            flask_app,
            dependencies=dependencies,
            route_settings=settings,
        ),
        raise_server_exceptions=False,
    )


def every_resource_path(ids: dict[str, object]) -> list[str]:
    return [
        "/v2/tax-benefit-models?country_id=us",
        "/v2/tax-benefit-models/by-country/us",
        f"/v2/tax-benefit-models/{ids['model_id']}?country_id=us",
        "/v2/tax-benefit-model-versions?country_id=us",
        f"/v2/tax-benefit-model-versions/{ids['model_version_id']}?country_id=us",
        "/v2/variables?country_id=us",
        f"/v2/variables/{ids['variable_id']}?country_id=us",
        "/v2/parameters?country_id=us",
        "/v2/parameters/children?country_id=us&parent_path=gov.example",
        f"/v2/parameters/{ids['parameter_id']}?country_id=us",
        "/v2/parameter-values?country_id=us",
        f"/v2/parameter-values/{ids['parameter_value_id']}?country_id=us",
        "/v2/datasets?country_id=us",
        f"/v2/datasets/{ids['dataset_id']}?country_id=us",
        "/v2/regions?country_id=us",
        "/v2/regions/by-code/us?country_id=us",
        f"/v2/regions/{ids['region_id']}?country_id=us",
        "/v2/economy-options?country_id=us",
        "/v2/model-catalog?country_id=us",
        "/v2/model-catalog/variables?country_id=us",
        "/v2/model-catalog/parameters?country_id=us&name=gov.example.rate",
    ]


def vary_values(response) -> set[str]:
    return {
        value.strip().lower()
        for value in response.headers.get("vary", "").split(",")
        if value.strip()
    }
