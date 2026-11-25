"""The dynamic parameter routes against a PostgreSQL catalog (C1 · 51).

Catalog publication stores each version's dynamic parameters and their
current-law values in their own tables (C1 · 50). These routes serve them
apart from policy parameters, including the US top-level ``simulation.*``
parameters, and read as API v1's runtime role.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from flask import Flask, jsonify
from policyengine_api.services.v2.metadata.dynamic_parameters.types import (
    DynamicParameterTreeLevel,
)
from sqlmodel import col

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.catalog.publication import publish_catalog
from policyengine_api.data.v2.catalog.publication_pruning import (
    prune_catalog_version,
)
from policyengine_api.data.v2.models import (
    DynamicParameter,
    ParameterNode,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.metadata.database_session import (
    MetadataDatabaseSession,
)
from policyengine_api.services.v2.metadata.services import V2MetadataService
from tests.fixtures.v2_catalog import (
    POLICYENGINE_VERSION,
    catalog_with_dynamic_parameters,
)
from tests.integration.catalog_publication_support import emptied_catalog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from tests.integration.conftest import ManagedV2Roles

PRUNED_VERSION = "5.0.1"
DYNAMIC_NAMES = {
    "us": [
        "gov.simulation.labor_supply_responses.elasticities.income",
        "simulation.marginal_tax_rate_delta",
    ],
    "uk": [
        "gov.dynamic.obr_labour_supply_assumptions",
        "gov.simulation.labour_supply_responses.income_elasticity",
    ],
}


@pytest.fixture
def published_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    with emptied_catalog(v2_owner_sessions) as sessions:
        publish_catalog(sessions, catalog_with_dynamic_parameters())
        yield sessions


def _client(sessions: sessionmaker[Session]) -> TestClient:
    flask_app = Flask(__name__)

    @flask_app.get("/<country_id>/metadata")
    def v1_metadata(country_id: str):
        return jsonify({"status": "ok", "result": {"country": country_id}})

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_metadata_reader_factory=lambda: V2MetadataService(
            MetadataDatabaseSession(sessions()),
            running_policyengine_version=POLICYENGINE_VERSION,
        ),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(flask_app, dependencies=dependencies, route_settings=settings)
    )


def _result(client: TestClient, path: str) -> dict:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text)
    result: dict = response.json()["result"]
    return result


def _us_version_id(sessions: sessionmaker[Session], version: str) -> UUID:
    with sessions() as session:
        version_id: UUID = session.execute(
            sa.select(col(TaxBenefitModelVersion.id))
            .join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
            .where(
                col(TaxBenefitModel.name) == "policyengine-us",
                col(TaxBenefitModelVersion.version) == version,
            )
        ).scalar_one()
    return version_id


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_postgres_dynamic_parameters_are_served_apart_from_policy_parameters(
    published_sessions: sessionmaker[Session], country_id: str
) -> None:
    client = _client(published_sessions)

    dynamic = _result(client, f"/v2/dynamic-parameters?country_id={country_id}")
    policy = _result(client, f"/v2/parameters?country_id={country_id}")
    named = _result(
        client,
        f"/v2/model-catalog/parameters?country_id={country_id}"
        f"&name={DYNAMIC_NAMES[country_id][0]}",
    )

    assert [item["name"] for item in dynamic["items"]] == DYNAMIC_NAMES[country_id]
    assert {item["name"] for item in policy["items"]}.isdisjoint(
        DYNAMIC_NAMES[country_id]
    )
    assert named["missing_names"] == [DYNAMIC_NAMES[country_id][0]]


def test_postgres_the_us_dynamic_tree_has_gov_and_top_level_simulation(
    published_sessions: sessionmaker[Session],
) -> None:
    client = _client(published_sessions)

    def level(query: str) -> list[tuple]:
        result = _result(
            client, f"/v2/dynamic-parameters/children?country_id=us{query}"
        )
        return [
            (item["path"], item["label"], item["type"], item["child_count"])
            for item in result["items"]
        ]

    assert level("") == [
        ("gov", "Gov", "node", 1),
        ("simulation", "Simulation settings", "node", 1),
    ]
    assert level("&settable=true") == level("")
    assert level("&parent_path=simulation") == [
        (
            "simulation.marginal_tax_rate_delta",
            "Marginal tax rate delta",
            "parameter",
            None,
        )
    ]
    assert level("&parent_path=gov.example") == []


def test_postgres_ids_resolve_within_their_own_category(
    published_sessions: sessionmaker[Session],
) -> None:
    client = _client(published_sessions)
    dynamic_parameter = _result(client, "/v2/dynamic-parameters?country_id=us")[
        "items"
    ][0]
    dynamic_value = _result(client, "/v2/dynamic-parameter-values?country_id=us")[
        "items"
    ][0]
    policy_parameter = _result(client, "/v2/parameters?country_id=us")["items"][0]
    policy_value = _result(client, "/v2/parameter-values?country_id=us")["items"][0]

    detail = _result(
        client, f"/v2/dynamic-parameters/{dynamic_parameter['id']}?country_id=us"
    )
    value_detail = _result(
        client, f"/v2/dynamic-parameter-values/{dynamic_value['id']}?country_id=us"
    )

    assert detail["item"] == dynamic_parameter
    assert value_detail["item"] == dynamic_value
    assert dynamic_value["parameter_id"] == dynamic_parameter["id"]
    for path in (
        f"/v2/dynamic-parameters/{policy_parameter['id']}?country_id=us",
        f"/v2/dynamic-parameter-values/{policy_value['id']}?country_id=us",
        f"/v2/parameters/{dynamic_parameter['id']}?country_id=us",
        f"/v2/parameter-values/{dynamic_value['id']}?country_id=us",
        f"/v2/dynamic-parameters/{dynamic_parameter['id']}?country_id=uk",
    ):
        response = client.get(path)
        assert response.status_code == 404, (path, response.text)


def test_postgres_the_catalog_route_serves_the_whole_category(
    published_sessions: sessionmaker[Session],
) -> None:
    client = _client(published_sessions)

    result = _result(client, "/v2/model-catalog/dynamic-parameters?country_id=us")
    listed = _result(client, "/v2/dynamic-parameters?country_id=us")["items"]

    assert result["policyengine_version"] == POLICYENGINE_VERSION
    assert result["catalog_format"] == 2
    assert [parameter["id"] for parameter in result["parameters"]] == [
        item["id"] for item in listed
    ]
    assert [parameter["values"] for parameter in result["parameters"]] == [
        [{"start_date": "2025-01-01T00:00:00Z", "end_date": None, "value": 0.1}],
        [{"start_date": "2025-01-01T00:00:00Z", "end_date": None, "value": 1000}],
    ]
    assert result["node_labels"] == {
        "gov.simulation": "Simulation",
        "gov.simulation.labor_supply_responses": "Labor supply responses",
        "gov.simulation.labor_supply_responses.elasticities": "Elasticities",
        "simulation": "Simulation settings",
    }


def test_postgres_a_pruned_version_answers_404_from_routes_of_pruned_data(
    published_sessions: sessionmaker[Session],
) -> None:
    publish_catalog(
        published_sessions,
        catalog_with_dynamic_parameters(policyengine_version=PRUNED_VERSION),
    )
    with published_sessions.begin() as session:
        prune_catalog_version(
            session, _us_version_id(published_sessions, PRUNED_VERSION)
        )
    client = _client(published_sessions)
    query = f"country_id=us&policyengine_version={PRUNED_VERSION}"

    for path in (
        f"/v2/dynamic-parameter-values?{query}",
        f"/v2/dynamic-parameters/children?{query}",
        f"/v2/model-catalog/dynamic-parameters?{query}",
    ):
        response = client.get(path)
        assert response.status_code == 404, (path, response.text)
        assert response.headers["cache-control"] == "no-store"
    assert len(_result(client, f"/v2/dynamic-parameters?{query}")["items"]) == 2


def test_postgres_the_dynamic_tree_reads_the_versions_enum_labels(
    published_sessions: sessionmaker[Session],
) -> None:
    breakdown = "gov.simulation.example_breakdown"
    version_id = _us_version_id(published_sessions, POLICYENGINE_VERSION)
    with published_sessions.begin() as session:
        session.add_all(
            [
                ParameterNode(
                    name=breakdown,
                    label="Example breakdown",
                    tax_benefit_model_version_id=version_id,
                ),
                DynamicParameter(
                    name=f"{breakdown}.SINGLE",
                    label="Example breakdown (Single filer)",
                    economy=True,
                    household=True,
                    tax_benefit_model_version_id=version_id,
                ),
                Variable(
                    name="example_filing_status",
                    entity="tax_unit",
                    enum_values=[{"value": "SINGLE", "label": "Single filer"}],
                    tax_benefit_model_version_id=version_id,
                ),
            ]
        )

    result = _result(
        _client(published_sessions),
        f"/v2/dynamic-parameters/children?country_id=us&parent_path={breakdown}",
    )

    assert [item["label"] for item in result["items"]] == ["SINGLE"]


def test_postgres_dynamic_parameter_reads_run_as_the_runtime_role(
    published_sessions: sessionmaker[Session],
    managed_v2_roles: ManagedV2Roles,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> None:
    """API v1's runtime role can make every read with its declared privileges."""
    runtime_sessions = v2_sessions_as_role(managed_v2_roles.runtime)
    with runtime_sessions() as session:
        reads = V2MetadataService(
            MetadataDatabaseSession(session),
            running_policyengine_version=POLICYENGINE_VERSION,
        ).dynamic_parameters
        parameters = reads.list_dynamic_parameters("us")
        values = reads.list_dynamic_parameter_values("us")
        children = reads.list_dynamic_parameter_children(
            "us", level=DynamicParameterTreeLevel(settable=True)
        )
        catalog = reads.get_catalog_dynamic_parameters("us")
        detail = reads.get_dynamic_parameter("us", parameters.items[0].id)
        value_detail = reads.get_dynamic_parameter_value("us", values.items[0].id)

    assert [item.name for item in parameters.items] == DYNAMIC_NAMES["us"]
    assert len(values.items) == 2
    assert [item.path for item in children.items] == ["gov", "simulation"]
    assert [parameter.name for parameter in catalog.parameters] == DYNAMIC_NAMES["us"]
    assert detail.item == parameters.items[0]
    assert value_detail.item == values.items[0]
