"""PostgreSQL-backed integration coverage for v2 metadata resource reads."""

from __future__ import annotations

import gzip
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask, jsonify
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.catalog.extraction import extract_catalog
from policyengine_api.data.v2.catalog.parameter_search_file import (
    country_search_file,
)
from policyengine_api.data.v2.catalog.publication import publish_catalog
from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterValue,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.metadata.database_session import (
    MetadataDatabaseSession,
)
from policyengine_api.services.v2.metadata.services import V2MetadataService
from policyengine_api.services.v2.metadata.types import ParameterTreeLevel
from tests.fixtures.v2_catalog import (
    POLICYENGINE_VERSION,
    bundle,
    installed_version,
    normalized_catalog,
    region_references,
    source_models,
)

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
        specification_provider=dict,
        v2_metadata_reader_factory=lambda: V2MetadataService(
            MetadataDatabaseSession(Session(engine)),
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
    [("us", 2, "Microcosm"), ("uk", 1, "Microcosm")],
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

    assert invalid.status_code == 422
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


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_postgres_model_catalog_serves_the_small_parts_of_a_version(
    published_engine: Engine,
    country_id: str,
) -> None:
    client = _client(published_engine)
    country = normalized_catalog().country(country_id)

    running = client.get("/v2/model-catalog", params={"country_id": country_id})
    named = client.get(
        "/v2/model-catalog",
        params={"country_id": country_id, "policyengine_version": POLICYENGINE_VERSION},
    )

    assert running.status_code == 200
    assert running.headers["cache-control"] == "public, max-age=300"
    assert named.headers["cache-control"] == "public, max-age=86400"
    assert running.headers["etag"] == named.headers["etag"]
    result = running.json()["result"]
    assert result["policyengine_version"] == POLICYENGINE_VERSION
    assert result["catalog_format"] == country.model_version.catalog_format
    assert result["entities"] == [
        {
            "key": entity.key,
            "plural": entity.plural,
            "is_person": entity.is_person,
        }
        for entity in country.model_version.entities
    ]
    assert result["basic_inputs"] == list(country.model_version.basic_inputs)
    assert [region["code"] for region in result["regions"]] == sorted(
        region.code for region in country.regions
    )
    assert [dataset["name"] for dataset in result["datasets"]] == sorted(
        dataset.name for dataset in country.datasets
    )
    assert [option["name"] for option in result["economy_options"]["region"]] == [
        region["code"] for region in result["regions"]
    ]
    assert "variables" not in result
    assert "parameters" not in result

    revalidated = client.get(
        "/v2/model-catalog",
        params={"country_id": country_id},
        headers={"If-None-Match": running.headers["etag"]},
    )
    assert revalidated.status_code == 304


def _us_model_version_id(engine: Engine):
    with Session(engine) as session:
        return session.exec(
            select(TaxBenefitModelVersion.id)
            .join(
                TaxBenefitModel, TaxBenefitModel.id == TaxBenefitModelVersion.model_id
            )
            .where(TaxBenefitModel.name == "policyengine-us")
        ).one()


def test_postgres_catalog_variables_carry_part_parameter_values_by_date(
    published_engine: Engine,
) -> None:
    model_version_id = _us_model_version_id(published_engine)
    parts_id = uuid4()
    with Session(published_engine) as session:
        session.add(
            Parameter(
                id=parts_id,
                tax_benefit_model_version_id=model_version_id,
                name="gov.example.parts",
                label="Income parts",
                economy=False,
                household=True,
            )
        )
        session.flush()
        session.add_all(
            [
                ParameterValue(
                    parameter_id=parts_id,
                    value_json=["employment_income"],
                    start_date=datetime(2024, 1, 1, tzinfo=UTC),
                ),
                ParameterValue(
                    parameter_id=parts_id,
                    value_json=["employment_income", "pension_income"],
                    start_date=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                Variable(
                    tax_benefit_model_version_id=model_version_id,
                    name="total_income",
                    entity="person",
                    data_type="float",
                    default_value=0,
                    adds=["employment_income"],
                    is_input_variable=False,
                    hidden_input=False,
                    module_name="household.income.total_income",
                    adds_parameter_path="gov.example.parts",
                ),
            ]
        )
        session.commit()
    client = _client(published_engine)

    response = client.get(
        "/v2/model-catalog/variables",
        params={"country_id": "us", "policyengine_version": POLICYENGINE_VERSION},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
    result = response.json()["result"]
    assert [variable["name"] for variable in result["variables"]] == [
        "employment_income",
        "total_income",
    ]
    assert result["variables"][0]["module_name"] == (
        "household.income.employment_income"
    )
    assert result["variables"][0]["unit"] == "currency-USD"
    assert result["variables"][0]["definition_period"] == "year"
    assert result["variables"][1]["adds_parameter_path"] == "gov.example.parts"
    assert result["part_parameter_values"] == {
        "gov.example.parts": [
            {
                "start_date": "2024-01-01T00:00:00Z",
                "end_date": None,
                "value": ["employment_income"],
            },
            {
                "start_date": "2026-01-01T00:00:00Z",
                "end_date": None,
                "value": ["employment_income", "pension_income"],
            },
        ]
    }
    uk = client.get("/v2/model-catalog/variables", params={"country_id": "uk"})
    assert [variable["name"] for variable in uk.json()["result"]["variables"]] == [
        "employment_income"
    ]
    assert uk.json()["result"]["part_parameter_values"] == {}


def test_postgres_catalog_parameters_load_values_and_breadcrumb_labels(
    published_engine: Engine,
) -> None:
    client = _client(published_engine)

    response = client.get(
        "/v2/model-catalog/parameters",
        params=[
            ("country_id", "us"),
            ("policyengine_version", POLICYENGINE_VERSION),
            ("name", "gov.example.rate"),
            ("name", "gov.removed.amount"),
        ],
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
    result = response.json()["result"]
    assert [parameter["name"] for parameter in result["parameters"]] == [
        "gov.example.rate"
    ]
    parameter = result["parameters"][0]
    assert (parameter["economy"], parameter["household"]) == (True, False)
    assert parameter["values"] == [
        {
            "start_date": "2025-01-01T00:00:00Z",
            "end_date": "2025-12-31T00:00:00Z",
            "value": 0.1,
        },
        {"start_date": "2026-01-01T00:00:00Z", "end_date": None, "value": 0.2},
    ]
    assert result["node_labels"] == {"gov.example": "Example policy"}
    assert result["missing_names"] == ["gov.removed.amount"]


def test_postgres_metadata_reads_send_no_transaction_statements(
    published_engine: Engine,
) -> None:
    # Each metadata read is one statement on rows a published catalog never
    # changes, so the read session runs in autocommit mode: psycopg then sends
    # no BEGIN before the reads and no ROLLBACK when the session closes. The
    # engine has one pooled connection, so the writer below must get the same
    # connection back in the ordinary, transactional mode.
    from psycopg.pq import TransactionStatus

    from policyengine_api.data.v2.database import build_v2_read_session_factory

    del published_engine  # publishes the catalog this pooled engine reads
    pooled_engine = create_engine(_disposable_url(), pool_size=1, max_overflow=0)
    read_connections: list[object] = []
    autocommit_modes: list[bool] = []

    def record_mode(connection, _cursor, _statement, *_args) -> None:
        dbapi_connection = connection.connection.dbapi_connection
        read_connections.append(dbapi_connection)
        autocommit_modes.append(dbapi_connection.autocommit)

    try:
        event.listen(pooled_engine, "before_cursor_execute", record_mode)
        service = V2MetadataService(
            MetadataDatabaseSession(build_v2_read_session_factory(pooled_engine)()),
            running_policyengine_version=POLICYENGINE_VERSION,
        )
        result = service.list_parameters("us")
        service.close()
        event.remove(pooled_engine, "before_cursor_execute", record_mode)

        with Session(pooled_engine) as writer:
            writer_connection = writer.connection().connection.dbapi_connection
            writer.execute(text("SELECT 1"))
            writer_status = writer_connection.info.transaction_status
            writer_autocommit = writer_connection.autocommit
    finally:
        pooled_engine.dispose()

    assert [item.name for item in result.items] == ["gov.example.rate"]
    assert autocommit_modes
    assert all(autocommit_modes)
    assert {id(connection) for connection in read_connections} == {
        id(writer_connection)
    }
    assert writer_autocommit is False
    assert writer_status == TransactionStatus.INTRANS


def test_postgres_production_metadata_reader_keeps_catalogs_and_responses(
    published_engine: Engine,
) -> None:
    # The production combination: autocommit read sessions, the process's
    # selected catalogs and its whole-version response cache.
    from policyengine_api.data.v2.database import build_v2_read_session_factory
    from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
        MetadataResponseCache,
    )
    from policyengine_api.services.v2.metadata.selected_catalogs import (
        SelectedCatalogStore,
    )

    read_factory = build_v2_read_session_factory(published_engine)
    selected_catalogs = SelectedCatalogStore()
    statements: list[str] = []

    def record_statement(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement)

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=dict,
        v2_metadata_reader_factory=lambda: V2MetadataService(
            MetadataDatabaseSession(read_factory()),
            running_policyengine_version=POLICYENGINE_VERSION,
            selected_catalogs=selected_catalogs,
        ),
        v2_metadata_response_cache=MetadataResponseCache(),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    client = TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        )
    )
    query = {"country_id": "us", "policyengine_version": POLICYENGINE_VERSION}

    event.listen(published_engine, "before_cursor_execute", record_statement)
    try:
        first_variables = client.get(
            "/v2/model-catalog/variables", params={"country_id": "us"}
        )
        statements_for_first = len(statements)
        repeated_variables = client.get("/v2/model-catalog/variables", params=query)
        statements_for_repeat = len(statements) - statements_for_first
        parameters = client.get(
            "/v2/parameters", params={"country_id": "us", "name": "gov.example.rate"}
        )
        statements_for_parameters = (
            len(statements) - statements_for_first - statements_for_repeat
        )
    finally:
        event.remove(published_engine, "before_cursor_execute", record_statement)

    assert first_variables.status_code == 200
    assert repeated_variables.content == first_variables.content
    assert repeated_variables.headers["etag"] == first_variables.headers["etag"]
    # The running version's selection and the variables read (the fixture's
    # variables name no parameter-defined parts, so no value read); then
    # nothing for the explicit request, which shares the kept response; then
    # only the parameter read, the running version's selection being kept.
    assert statements_for_first == 2
    assert statements_for_repeat == 0
    assert statements_for_parameters == 1
    assert [item["name"] for item in parameters.json()["result"]["items"]] == [
        "gov.example.rate"
    ]
    assert selected_catalogs.get(("us", None)) is not None


@pytest.mark.parametrize(
    "case",
    [
        # Read for 31 December, headers written after midnight: not reusable.
        (
            datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            [0.1],
            "public, max-age=0",
        ),
        (
            datetime(2025, 12, 31, 12, 0, tzinfo=UTC),
            datetime(2025, 12, 31, 12, 0, tzinfo=UTC),
            [0.1],
            "public, max-age=43200",
        ),
        (
            datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            [0.2],
            "public, max-age=86400",
        ),
    ],
)
def test_postgres_current_values_and_their_lifetime_use_one_instant(
    published_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[datetime, datetime, list[float], str],
) -> None:
    from policyengine_api.fastapi_routes.v2.metadata import common

    read_instant, header_instant, expected_values, expected_cache_control = case
    instants = iter([read_instant, header_instant])
    monkeypatch.setattr(common, "utc_now", lambda: next(instants))

    response = _client(published_engine).get(
        "/v2/parameter-values",
        params={
            "country_id": "us",
            "policyengine_version": POLICYENGINE_VERSION,
            "current": "true",
        },
    )

    assert response.status_code == 200
    assert [item["value"] for item in response.json()["result"]["items"]] == (
        expected_values
    )
    assert response.headers["cache-control"] == expected_cache_control


SCHEDULE = "gov.hmrc.income_tax.rates.uk"


def _catalog_with_a_bracket_schedule():
    """Return the fixture catalog with a UK-style income tax schedule added.

    The schedule has a stored node row; a second schedule has none.
    """
    models = source_models()
    uk = models["uk"]
    nodes = [
        SimpleNamespace(name=SCHEDULE, label="Income Tax main rates", description=None)
    ]
    parameters = [
        SimpleNamespace(
            name=name,
            label=label,
            description=None,
            data_type=float,
            unit="/1",
            economy=economy,
            household=household,
            parameter_values=[
                SimpleNamespace(
                    value=0.2,
                    start_date=datetime(2025, 1, 1, tzinfo=UTC),
                    end_date=None,
                )
            ],
        )
        for name, label, economy, household in (
            (f"{SCHEDULE}[0].rate", "Basic rate", True, True),
            (f"{SCHEDULE}[0].threshold", "Basic rate threshold", True, True),
            (f"{SCHEDULE}[1].rate", "Higher rate", True, True),
            (f"{SCHEDULE}[1].threshold", "Higher rate threshold", False, False),
            ("gov.hmrc.income_tax.rates.dividends[0].rate", None, True, False),
        )
    ]
    uk.parameter_nodes.extend(nodes)
    uk.parameters.extend(parameters)
    uk.parameter_nodes_by_name.update({node.name: node for node in nodes})
    uk.parameters_by_name.update(
        {parameter.name: parameter for parameter in parameters}
    )
    return extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
        region_references=region_references(),
    )


def _items(response) -> list[tuple]:
    assert response.status_code == 200, response.text
    return [
        (item["path"], item["label"], item["type"], item["child_count"])
        for item in response.json()["result"]["items"]
    ]


def test_postgres_parameter_tree_nests_schedules_and_filters_reform_changes(
    published_engine: Engine,
) -> None:
    with published_engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    publish_catalog(published_engine, _catalog_with_a_bracket_schedule())
    client = _client(published_engine)
    query = {"country_id": "uk"}

    rates = client.get(
        "/v2/parameters/children",
        params={**query, "parent_path": "gov.hmrc.income_tax.rates"},
    )
    schedule = client.get(
        "/v2/parameters/children", params={**query, "parent_path": SCHEDULE}
    )
    bracket = client.get(
        "/v2/parameters/children",
        params={**query, "parent_path": f"{SCHEDULE}[1]"},
    )
    reform_bracket = client.get(
        "/v2/parameters/children",
        params={
            **query,
            "parent_path": f"{SCHEDULE}[1]",
            "reform_changeable": "true",
        },
    )
    reform_rates = client.get(
        "/v2/parameters/children",
        params={
            **query,
            "parent_path": "gov.hmrc.income_tax.rates",
            "reform_changeable": "true",
        },
    )

    assert _items(rates) == [
        ("gov.hmrc.income_tax.rates.dividends", "Dividends", "node", 1),
        (SCHEDULE, "Income Tax main rates", "node", 2),
    ]
    assert _items(schedule) == [
        (f"{SCHEDULE}[0]", "Bracket 1", "node", 2),
        (f"{SCHEDULE}[1]", "Bracket 2", "node", 2),
    ]
    assert _items(bracket) == [
        (f"{SCHEDULE}[1].rate", "Higher rate", "parameter", None),
        (f"{SCHEDULE}[1].threshold", "Higher rate threshold", "parameter", None),
    ]
    assert _items(reform_bracket) == [
        (f"{SCHEDULE}[1].rate", "Higher rate", "parameter", None),
    ]
    assert _items(reform_rates) == [
        ("gov.hmrc.income_tax.rates.dividends", "Dividends", "node", 1),
        (SCHEDULE, "Income Tax main rates", "node", 2),
    ]
    leaf = bracket.json()["result"]["items"][0]["parameter"]
    assert leaf["name"] == f"{SCHEDULE}[1].rate"


def test_postgres_parameter_tree_reads_as_the_runtime_role(
    published_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """The Public API's runtime role can read the tree with its declared privileges."""
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    try:
        with Session(runtime_engine) as session:
            result = V2MetadataService(
                MetadataDatabaseSession(session),
                running_policyengine_version=POLICYENGINE_VERSION,
            ).list_parameter_children(
                "us",
                level=ParameterTreeLevel(parent_path="gov", reform_changeable=True),
            )
    finally:
        runtime_engine.dispose()

    assert [(item.path, item.child_count) for item in result.items] == [
        ("gov.example", 1)
    ]


def _catalog_shaped_like_policyengine_py_output():
    """Return the fixture catalog with US records shaped like PolicyEngine.py's.

    Bracket parameters carry the labels PolicyEngine.py generates, and a
    breakdown parameter its parent's label with the key. One schedule has no
    node row, as the locked PolicyEngine.py publishes; the other has one with
    its label, as the release that publishes schedules will.
    """
    models = source_models()
    us = models["us"]
    nodes = [
        SimpleNamespace(
            name="gov.irs.deductions.standard.amount",
            label="Standard deduction",
            description=None,
        ),
        SimpleNamespace(
            name="gov.aca.age_curves.ak",
            label="ACA premium age curve factors - AK",
            description=None,
        ),
    ]
    labelled_parameters = [
        (f"gov.aca.age_curves.{state}[{index}].{field}", f"{label} ({tier} {field})")
        for state, label in (
            ("al", "ACA premium age curve factors - AL"),
            ("ak", "ACA premium age curve factors - AK"),
        )
        for index, tier in ((0, "tier 1"), (1, "tier 2"))
        for field in ("amount", "threshold")
    ] + [
        ("gov.irs.deductions.standard.amount.SINGLE", "Standard deduction (Single)"),
        ("gov.irs.deductions.standard.amount.JOINT", "Standard deduction (Joint)"),
    ]
    parameters = [
        SimpleNamespace(
            name=name,
            label=label,
            description=None,
            data_type=float,
            unit="currency-USD",
            economy=True,
            household=True,
            parameter_values=[
                SimpleNamespace(
                    value=1.0,
                    start_date=datetime(2025, 1, 1, tzinfo=UTC),
                    end_date=None,
                )
            ],
        )
        for name, label in labelled_parameters
    ]
    us.parameter_nodes.extend(nodes)
    us.parameters.extend(parameters)
    us.parameter_nodes_by_name.update({node.name: node for node in nodes})
    us.parameters_by_name.update(
        {parameter.name: parameter for parameter in parameters}
    )
    return extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
        region_references=region_references(),
    )


def test_postgres_parameter_tree_from_records_shaped_like_policyengine_py(
    published_engine: Engine,
) -> None:
    with published_engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    publish_catalog(published_engine, _catalog_shaped_like_policyengine_py_output())
    client = _client(published_engine)

    def level(parent_path: str) -> list[tuple]:
        return _items(
            client.get(
                "/v2/parameters/children",
                params={"country_id": "us", "parent_path": parent_path},
            )
        )

    assert level("gov.aca.age_curves") == [
        ("gov.aca.age_curves.ak", "ACA premium age curve factors - AK", "node", 2),
        ("gov.aca.age_curves.al", "Al", "node", 2),
    ]
    assert level("gov.aca.age_curves.al") == [
        ("gov.aca.age_curves.al[0]", "Bracket 1", "node", 2),
        ("gov.aca.age_curves.al[1]", "Bracket 2", "node", 2),
    ]
    assert level("gov.aca.age_curves.al[1]") == [
        (
            "gov.aca.age_curves.al[1].amount",
            "ACA premium age curve factors - AL (tier 2 amount)",
            "parameter",
            None,
        ),
        (
            "gov.aca.age_curves.al[1].threshold",
            "ACA premium age curve factors - AL (tier 2 threshold)",
            "parameter",
            None,
        ),
    ]
    assert level("gov.irs.deductions.standard") == [
        ("gov.irs.deductions.standard.amount", "Standard deduction", "node", 2),
    ]
    assert level("gov.irs.deductions.standard.amount") == [
        (
            "gov.irs.deductions.standard.amount.JOINT",
            "Standard deduction (Joint)",
            "parameter",
            None,
        ),
        (
            "gov.irs.deductions.standard.amount.SINGLE",
            "Standard deduction (Single)",
            "parameter",
            None,
        ),
    ]


def test_postgres_a_version_stored_before_format_2_returns_the_tree_503(
    published_engine: Engine,
) -> None:
    """A version stored before catalog format 2 gets no tree on republication.

    Its parameter tree request returns 503 with the message naming it.
    """
    with published_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE tax_benefit_model_versions SET catalog_format = NULL, "
                "entities = NULL, basic_inputs = NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE variables SET is_input_variable = NULL, hidden_input = NULL, "
                "module_name = NULL, adds_parameter_path = NULL, "
                "subtracts_parameter_path = NULL, enum_values = NULL, "
                "unit = NULL, definition_period = NULL"
            )
        )
        connection.execute(
            text("UPDATE parameters SET economy = NULL, household = NULL")
        )
        connection.execute(text("DELETE FROM parameter_tree_children"))
    evidence = publish_catalog(published_engine, normalized_catalog())

    response = _client(published_engine).get(
        "/v2/parameters/children",
        params={"country_id": "us", "policyengine_version": POLICYENGINE_VERSION},
    )

    assert evidence.parameter_trees_written == ()
    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": (
            f"catalog version {POLICYENGINE_VERSION} has no parameter tree: "
            "catalog publication writes trees only for the versions it publishes "
            "and for the installed version with catalog format 2"
        ),
    }
    assert "cache-control" not in response.headers


def test_postgres_search_file_is_served_with_its_etag_and_revalidated(
    published_engine: Engine,
) -> None:
    client = _client(published_engine)
    expected = country_search_file(normalized_catalog().country("uk"))

    response = client.get(
        "/v2/parameters/search-file",
        params={"country_id": "uk", "policyengine_version": POLICYENGINE_VERSION},
        headers={"Accept-Encoding": "gzip"},
    )
    revalidated = client.get(
        "/v2/parameters/search-file",
        params={"country_id": "uk", "policyengine_version": POLICYENGINE_VERSION},
        headers={
            "Accept-Encoding": "gzip",
            "If-None-Match": response.headers["etag"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.json() == expected
    assert revalidated.status_code == 304
    assert revalidated.headers["etag"] == response.headers["etag"]


def test_postgres_search_file_of_a_version_without_one_is_unavailable(
    published_engine: Engine,
) -> None:
    with published_engine.begin() as connection:
        connection.execute(text("DELETE FROM parameter_search_files"))

    response = _client(published_engine).get(
        "/v2/parameters/search-file", params={"country_id": "us"}
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": (
            f"catalog version {POLICYENGINE_VERSION} has no parameter search "
            "file: only catalog format 2 versions that catalog publication has "
            "published, or run with installed, since search files were added have "
            "one"
        ),
    }


def test_postgres_search_file_reads_as_the_runtime_role(
    published_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """The Public API's runtime role reads the file with its declared privileges."""
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    try:
        with Session(runtime_engine) as session:
            service = V2MetadataService(
                MetadataDatabaseSession(session),
                running_policyengine_version=POLICYENGINE_VERSION,
            )
            search_file = service.get_parameter_search_file("us")
            content_sha256 = service.get_parameter_search_file_hash("us")
    finally:
        runtime_engine.dispose()

    assert json.loads(gzip.decompress(search_file.compressed_content)) == (
        country_search_file(normalized_catalog().country("us"))
    )
    assert content_sha256 == search_file.content_sha256


def test_postgres_search_file_of_an_unknown_catalog_version_is_absent(
    published_engine: Engine,
) -> None:
    response = _client(published_engine).get(
        "/v2/parameters/search-file",
        params={"country_id": "us", "policyengine_version": "99.0.0"},
    )

    assert response.status_code == 404
    assert response.json()["status"] == "error"
