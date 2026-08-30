"""PostgreSQL-backed integration coverage for v2 metadata resource reads."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask, jsonify
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.catalog.publication import publish_catalog
from policyengine_api.data.v2.catalog.query import V2MetadataQueryService
from policyengine_api.data.v2.models import (
    Dataset,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION, normalized_catalog


REPO = Path(__file__).parents[2]
DISPOSABLE_DATABASE = "policyengine_v2_alembic_test"


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    url = make_url(database_url)
    if url.database != DISPOSABLE_DATABASE or url.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
    }:
        pytest.fail("v2 metadata route tests require disposable local PostgreSQL")
    return database_url


@pytest.fixture
def published_engine() -> Engine:
    database_url = _disposable_url()
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    publish_catalog(engine, normalized_catalog())
    yield engine
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    engine.dispose()


def _client(engine: Engine) -> TestClient:
    flask_app = Flask(__name__)

    @flask_app.get("/<country_id>/metadata")
    def v1_metadata(country_id: str):
        return jsonify({"status": "ok", "result": {"country": country_id}})

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=lambda: {},
        v2_metadata_reader_factory=lambda: V2MetadataQueryService(
            Session(engine),
            running_policyengine_version=POLICYENGINE_VERSION,
        ),
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
        )
    )


def _catalog_counts(engine: Engine) -> tuple[int, ...]:
    with engine.connect() as connection:
        return tuple(
            connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM variables),
                        (SELECT count(*) FROM parameters),
                        (SELECT count(*) FROM parameter_values),
                        (SELECT count(*) FROM datasets),
                        (SELECT count(*) FROM regions)
                    """
                )
            ).one()
        )


@pytest.mark.parametrize(
    ("country_id", "current_law_id", "dataset_label"),
    [("us", 2, "Microcosm"), ("uk", 1, "Enhanced FRS")],
)
def test_postgres_resource_collections_are_separate_and_read_only(
    published_engine: Engine,
    country_id: str,
    current_law_id: int,
    dataset_label: str,
) -> None:
    client = _client(published_engine)
    before = _catalog_counts(published_engine)
    query = {"country_id": country_id}

    models = client.get("/v2/tax-benefit-models", params=query)
    model_versions = client.get("/v2/tax-benefit-model-versions", params=query)
    variables = client.get("/v2/variables", params=query)
    repeated_variables = client.get("/v2/variables", params=query)
    parameters = client.get("/v2/parameters", params=query)
    parameter_values = client.get("/v2/parameter-values", params=query)
    datasets = client.get("/v2/datasets", params=query)
    regions = client.get("/v2/regions", params=query)
    options = client.get("/v2/economy-options", params=query)

    responses = (
        models,
        model_versions,
        variables,
        parameters,
        parameter_values,
        datasets,
        regions,
        options,
    )
    assert all(response.status_code == 200 for response in responses)
    for response in responses:
        assert response.json()["result"]["policyengine_version"] == (
            POLICYENGINE_VERSION
        )

    assert models.json()["result"]["items"][0]["name"] == (f"policyengine-{country_id}")
    assert model_versions.json()["result"]["items"][0]["version"] == (
        POLICYENGINE_VERSION
    )
    assert variables.json()["result"]["items"]
    assert repeated_variables.json() == variables.json()
    parameter_items = parameters.json()["result"]["items"]
    assert parameter_items
    assert "values" not in parameter_items[0]
    assert parameter_values.json()["result"]["items"]
    assert datasets.json()["result"]["items"]
    assert regions.json()["result"]["items"]
    assert all(
        not dataset["is_output_dataset"] and dataset["storage_path"] is None
        for dataset in datasets.json()["result"]["items"]
    )
    option_result = options.json()["result"]
    assert option_result["current_law_id"] == current_law_id
    assert option_result["datasets"][0]["label"] == dataset_label
    assert all(
        isinstance(period["name"], int) and isinstance(period["label"], str)
        for period in option_result["time_period"]
    )
    assert _catalog_counts(published_engine) == before


def test_postgres_parameter_tree_returns_direct_children_and_leaf_details(
    published_engine: Engine,
) -> None:
    client = _client(published_engine)
    query = {"country_id": "us"}

    root = client.get("/v2/parameters/children", params=query)
    government = client.get(
        "/v2/parameters/children",
        params={**query, "parent_path": "gov"},
    )
    example = client.get(
        "/v2/parameters/children",
        params={**query, "parent_path": "gov.example"},
    )

    assert root.status_code == government.status_code == example.status_code == 200
    assert [
        (item["path"], item["type"]) for item in root.json()["result"]["items"]
    ] == [("gov", "node")]
    assert [
        (item["path"], item["type"]) for item in government.json()["result"]["items"]
    ] == [("gov.example", "node")]
    leaf = example.json()["result"]["items"][0]
    assert leaf["path"] == "gov.example.rate"
    assert leaf["type"] == "parameter"
    assert leaf["parameter"]["name"] == "gov.example.rate"


def test_postgres_collection_ids_resolve_through_detail_routes(
    published_engine: Engine,
) -> None:
    client = _client(published_engine)
    query = {"country_id": "us"}
    resources = (
        ("tax-benefit-models", "model_id"),
        ("tax-benefit-model-versions", "version_id"),
        ("variables", "variable_id"),
        ("parameters", "parameter_id"),
        ("parameter-values", "value_id"),
        ("datasets", "dataset_id"),
        ("regions", "region_id"),
    )

    for resource, _parameter_name in resources:
        collection = client.get(f"/v2/{resource}", params=query)
        resource_id = collection.json()["result"]["items"][0]["id"]
        detail = client.get(f"/v2/{resource}/{resource_id}", params=query)
        assert detail.status_code == 200
        assert detail.json()["result"]["item"]["id"] == resource_id

    by_country = client.get("/v2/tax-benefit-models/by-country/us")
    by_code = client.get("/v2/regions/by-code/state/ca", params=query)
    assert by_country.status_code == 200
    assert by_country.json()["result"]["model"]["name"] == "policyengine-us"
    assert by_code.status_code == 200
    assert by_code.json()["result"]["item"]["code"] == "state/ca"


def test_postgres_dataset_collection_excludes_an_existing_output(
    published_engine: Engine,
) -> None:
    with Session(published_engine) as session:
        model = session.exec(
            select(TaxBenefitModel).where(TaxBenefitModel.name == "policyengine-us")
        ).one()
        session.add(
            Dataset(
                id=uuid4(),
                tax_benefit_model_version_id=session.exec(
                    select(TaxBenefitModelVersion).where(
                        TaxBenefitModelVersion.model_id == model.id,
                        TaxBenefitModelVersion.version == POLICYENGINE_VERSION,
                    )
                )
                .one()
                .id,
                name="existing-output",
                description="Generated output",
                storage_path="private-output-reference",
                year=2026,
                is_output_dataset=True,
            )
        )
        session.commit()

    response = _client(published_engine).get(
        "/v2/datasets",
        params={"country_id": "us"},
    )

    assert response.status_code == 200
    assert "existing-output" not in {
        dataset["name"] for dataset in response.json()["result"]["items"]
    }


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_postgres_resources_default_to_running_version_and_accept_exact_override(
    published_engine: Engine,
    country_id: str,
) -> None:
    publish_catalog(
        published_engine,
        normalized_catalog(policyengine_version="5.0.5"),
    )
    client = _client(published_engine)

    default_response = client.get(
        "/v2/variables",
        params={"country_id": country_id},
    )
    selected_response = client.get(
        "/v2/variables",
        params={"country_id": country_id, "policyengine_version": "5.0.5"},
    )

    assert default_response.status_code == selected_response.status_code == 200
    default_result = default_response.json()["result"]
    selected_result = selected_response.json()["result"]
    assert default_result["policyengine_version"] == POLICYENGINE_VERSION
    assert selected_result["policyengine_version"] == "5.0.5"
    assert {item["id"] for item in default_result["items"]}.isdisjoint(
        item["id"] for item in selected_result["items"]
    )


def test_postgres_resources_distinguish_invalid_and_absent_versions(
    published_engine: Engine,
) -> None:
    client = _client(published_engine)

    invalid = client.get(
        "/v2/variables",
        params={"country_id": "us", "policyengine_version": "not a version"},
    )
    absent = client.get(
        "/v2/variables",
        params={"country_id": "us", "policyengine_version": "4.99.0"},
    )

    assert invalid.status_code == 400
    assert invalid.json()["status"] == "error"
    assert invalid.json()["message"]
    assert absent.status_code == 404
    assert absent.json()["status"] == "error"
    assert absent.json()["message"]


def test_postgres_parameter_collection_remains_available_without_values(
    published_engine: Engine,
) -> None:
    with published_engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM parameter_values
                WHERE parameter_id IN (
                    SELECT parameter.id
                    FROM parameters AS parameter
                    JOIN tax_benefit_model_versions AS model_version
                      ON model_version.id = parameter.tax_benefit_model_version_id
                    JOIN tax_benefit_models AS model
                      ON model.id = model_version.model_id
                    WHERE model.name = 'policyengine-us'
                )
                """
            )
        )

    client = _client(published_engine)
    parameters = client.get("/v2/parameters", params={"country_id": "us"})
    values = client.get("/v2/parameter-values", params={"country_id": "us"})

    assert parameters.status_code == values.status_code == 200
    assert parameters.json()["result"]["items"]
    assert values.json()["result"]["items"] == []
