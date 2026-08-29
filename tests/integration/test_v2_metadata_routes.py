"""Postgres-backed integration coverage for v2 metadata preview reads."""

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
        pytest.fail("v2 preview route tests require disposable local Postgres")
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


def test_postgres_preview_returns_complete_us_and_uk_catalogs_without_writes(
    published_engine: Engine,
) -> None:
    client = _client(published_engine)
    with published_engine.connect() as connection:
        before = connection.execute(
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

    us = client.get("/v2/us/metadata")
    uk = client.get("/v2/uk/metadata")

    assert us.status_code == uk.status_code == 200
    assert us.json()["result"]["current_law_id"] == 2
    assert uk.json()["result"]["current_law_id"] == 1
    for country_id, response in (("us", us), ("uk", uk)):
        result = response.json()["result"]
        assert result["model"]["name"] == f"policyengine-{country_id}"
        assert result["model_version"]["version"] == POLICYENGINE_VERSION
        assert result["variables"]
        assert result["parameter_nodes"]
        assert result["parameters"]
        assert result["parameters"][0]["values"]
        assert result["datasets"]
        assert result["regions"]
        assert all(
            not dataset["is_output_dataset"] and dataset["storage_path"] is None
            for dataset in result["datasets"]
        )
        assert all(
            isinstance(period["name"], int) and isinstance(period["label"], str)
            for period in result["economy_options"]["time_period"]
        )

    with published_engine.connect() as connection:
        after = connection.execute(
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
    assert after == before


def test_postgres_preview_excludes_an_existing_output_dataset(
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

    response = _client(published_engine).get("/v2/us/metadata")

    assert response.status_code == 200
    assert "existing-output" not in {
        dataset["name"] for dataset in response.json()["result"]["datasets"]
    }


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_postgres_preview_defaults_to_running_version_and_accepts_exact_version(
    published_engine: Engine,
    country_id: str,
) -> None:
    publish_catalog(
        published_engine,
        normalized_catalog(policyengine_version="5.0.5"),
    )
    client = _client(published_engine)

    default_response = client.get(f"/v2/{country_id}/metadata")
    selected_response = client.get(
        f"/v2/{country_id}/metadata",
        params={"policyengine_version": "5.0.5"},
    )

    assert default_response.status_code == selected_response.status_code == 200
    default_result = default_response.json()["result"]
    selected_result = selected_response.json()["result"]
    assert default_result["model_version"]["version"] == POLICYENGINE_VERSION
    assert selected_result["model_version"]["version"] == "5.0.5"
    assert (
        default_result["model_version"]["id"] != selected_result["model_version"]["id"]
    )
    assert {dataset["id"] for dataset in default_result["datasets"]}.isdisjoint(
        dataset["id"] for dataset in selected_result["datasets"]
    )
    assert {region["id"] for region in default_result["regions"]}.isdisjoint(
        region["id"] for region in selected_result["regions"]
    )


def test_postgres_preview_distinguishes_invalid_and_absent_versions(
    published_engine: Engine,
) -> None:
    client = _client(published_engine)

    invalid = client.get(
        "/v2/us/metadata",
        params={"policyengine_version": "not a version"},
    )
    absent = client.get(
        "/v2/us/metadata",
        params={"policyengine_version": "4.99.0"},
    )

    assert invalid.status_code == 400
    assert invalid.json()["status"] == "error"
    assert invalid.json()["message"]
    assert absent.status_code == 404
    assert absent.json()["status"] == "error"
    assert absent.json()["message"]
