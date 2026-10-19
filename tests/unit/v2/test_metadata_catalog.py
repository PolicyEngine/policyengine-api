"""The bulk v2 metadata catalog: one document per country and catalog version."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Parameter,
    ParameterValue,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataCatalogResponse,
)
from policyengine_api.services.v2.metadata.catalog_cache import MetadataCatalogCache
from policyengine_api.services.v2.metadata.database_session import (
    MetadataDatabaseSession,
)
from policyengine_api.services.v2.metadata.services import V2MetadataService
from policyengine_api.services.v2.metadata.types import MetadataCatalogDocument
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION, normalized_catalog
from tests.unit.v2.test_metadata_service import _insert_country

LATER_POLICYENGINE_VERSION = "5.0.5"


@pytest.fixture
def catalog_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(engine)
    with Session(engine) as session:
        for country in normalized_catalog().countries:
            _insert_country(session, country, include_model=True)
        session.commit()

    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _service(
    session: Session, catalog_cache: MetadataCatalogCache | None = None
) -> V2MetadataService:
    return V2MetadataService(
        MetadataDatabaseSession(session),
        running_policyengine_version=POLICYENGINE_VERSION,
        catalog_cache=catalog_cache,
    )


def _us_parameter(session: Session, name: str = "gov.example.rate") -> Parameter:
    return session.exec(
        select(Parameter)
        .join(
            TaxBenefitModelVersion,
            TaxBenefitModelVersion.id == Parameter.tax_benefit_model_version_id,
        )
        .join(TaxBenefitModel, TaxBenefitModel.id == TaxBenefitModelVersion.model_id)
        .where(
            TaxBenefitModel.name == "policyengine-us",
            TaxBenefitModelVersion.version == POLICYENGINE_VERSION,
            Parameter.name == name,
        )
    ).one()


def _result(document: MetadataCatalogDocument) -> dict:
    envelope = json.loads(document.body)
    assert envelope["status"] == "ok"
    assert envelope["message"] is None
    return envelope["result"]


def test_catalog_holds_every_node_parameter_value_and_variable(
    catalog_session: Session,
) -> None:
    document = _service(catalog_session).get_model_catalog("us")
    result = _result(document)
    parameter = _us_parameter(catalog_session)

    assert document.country_id == "us"
    assert document.policyengine_version == POLICYENGINE_VERSION
    assert result["policyengine_version"] == POLICYENGINE_VERSION
    assert result["parameter_nodes"] == [
        {
            "name": "gov.example",
            "label": "Example policy",
            "description": "Example policy parameters",
        }
    ]
    assert result["parameters"] == [
        {
            "id": str(parameter.id),
            "name": "gov.example.rate",
            "label": "Example rate",
            "description": "An example rate",
            "data_type": "float",
            "unit": "/1",
            "values": {"2025-01-01": 0.1, "2026-01-01": 0.2},
        }
    ]
    assert [variable["name"] for variable in result["variables"]] == [
        "employment_income"
    ]
    assert result["variables"][0]["entity"] == "person"
    assert result["variables"][0]["label"] == "Employment income"


def test_catalog_body_matches_the_published_response_schema(
    catalog_session: Session,
) -> None:
    document = _service(catalog_session).get_model_catalog("uk")

    response = MetadataCatalogResponse.model_validate_json(document.body)

    assert response.result.policyengine_version == POLICYENGINE_VERSION
    assert [item.name for item in response.result.parameters] == ["gov.example.rate"]


def test_catalog_values_are_current_law_only_and_ordered_by_start_date(
    catalog_session: Session,
) -> None:
    parameter = _us_parameter(catalog_session)
    catalog_session.add_all(
        [
            ParameterValue(
                id=uuid4(),
                parameter_id=parameter.id,
                value_json=0.9,
                start_date=datetime(2024, 1, 1, tzinfo=UTC),
                end_date=None,
                policy_id=uuid4(),
            ),
            Parameter(
                id=uuid4(),
                name="gov.example.allowance",
                label=None,
                description=None,
                data_type="bool",
                unit=None,
                tax_benefit_model_version_id=parameter.tax_benefit_model_version_id,
            ),
        ]
    )
    catalog_session.commit()

    result = _result(_service(catalog_session).get_model_catalog("us"))

    assert [item["name"] for item in result["parameters"]] == [
        "gov.example.allowance",
        "gov.example.rate",
    ]
    assert result["parameters"][0]["values"] == {}
    assert list(result["parameters"][1]["values"].items()) == [
        ("2025-01-01", 0.1),
        ("2026-01-01", 0.2),
    ]


def test_catalog_for_an_explicit_version_reads_that_version(
    catalog_session: Session,
) -> None:
    later = normalized_catalog(policyengine_version=LATER_POLICYENGINE_VERSION)
    _insert_country(catalog_session, later.country("us"), include_model=False)
    catalog_session.commit()

    running = _service(catalog_session).get_model_catalog("us")
    selected = _service(catalog_session).get_model_catalog(
        "us", LATER_POLICYENGINE_VERSION
    )

    assert running.policyengine_version == POLICYENGINE_VERSION
    assert selected.policyengine_version == LATER_POLICYENGINE_VERSION
    assert (
        _result(selected)["parameters"][0]["id"]
        != _result(running)["parameters"][0]["id"]
    )


def test_catalog_is_built_once_per_country_and_version(
    catalog_session: Session,
) -> None:
    statements: list[str] = []

    def record_statement(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement.lower())

    catalog_cache = MetadataCatalogCache()
    bind = catalog_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        first = _service(catalog_session, catalog_cache).get_model_catalog("us")
        statements_for_first_build = len(statements)
        second = _service(catalog_session, catalog_cache).get_model_catalog("us")
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    later_statements = statements[statements_for_first_build:]
    assert second is first
    assert later_statements
    assert all("parameter_values" not in statement for statement in later_statements)
    assert all("from variables" not in statement for statement in later_statements)


def _document(country_id: str, policyengine_version: str) -> MetadataCatalogDocument:
    return MetadataCatalogDocument(
        country_id=country_id,
        policyengine_version=policyengine_version,
        body=f"{country_id}-{policyengine_version}".encode(),
    )


def test_cache_evicts_the_least_recently_used_document() -> None:
    catalog_cache = MetadataCatalogCache(capacity=2)
    builds: list[tuple[str, str]] = []

    def build(country_id: str, version: str):
        def build_document() -> MetadataCatalogDocument:
            builds.append((country_id, version))
            return _document(country_id, version)

        return build_document

    catalog_cache.get_or_build(("us", "1.0.0"), build("us", "1.0.0"))
    catalog_cache.get_or_build(("uk", "1.0.0"), build("uk", "1.0.0"))
    catalog_cache.get_or_build(("us", "1.0.0"), build("us", "1.0.0"))
    catalog_cache.get_or_build(("us", "2.0.0"), build("us", "2.0.0"))
    catalog_cache.get_or_build(("us", "1.0.0"), build("us", "1.0.0"))
    catalog_cache.get_or_build(("uk", "1.0.0"), build("uk", "1.0.0"))

    assert builds == [
        ("us", "1.0.0"),
        ("uk", "1.0.0"),
        ("us", "2.0.0"),
        ("uk", "1.0.0"),
    ]


def test_cache_builds_once_for_concurrent_requests() -> None:
    catalog_cache = MetadataCatalogCache()
    build_started = threading.Event()
    release_build = threading.Event()
    build_count = 0
    results: list[MetadataCatalogDocument] = []

    def slow_build() -> MetadataCatalogDocument:
        nonlocal build_count
        build_count += 1
        build_started.set()
        release_build.wait(timeout=5)
        return _document("us", "1.0.0")

    def request_document() -> None:
        results.append(catalog_cache.get_or_build(("us", "1.0.0"), slow_build))

    first_request = threading.Thread(target=request_document)
    first_request.start()
    assert build_started.wait(timeout=5)
    waiting_requests = [threading.Thread(target=request_document) for _ in range(3)]
    for request in waiting_requests:
        request.start()
    release_build.set()
    for request in [first_request, *waiting_requests]:
        request.join(timeout=5)

    assert build_count == 1
    assert len(results) == 4
    assert all(result is results[0] for result in results)


def test_cache_does_not_keep_a_failed_build() -> None:
    catalog_cache = MetadataCatalogCache()

    def failing_build() -> MetadataCatalogDocument:
        msg = "database unavailable"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="database unavailable"):
        catalog_cache.get_or_build(("us", "1.0.0"), failing_build)
    document = catalog_cache.get_or_build(
        ("us", "1.0.0"), lambda: _document("us", "1.0.0")
    )

    assert document.body == b"us-1.0.0"
