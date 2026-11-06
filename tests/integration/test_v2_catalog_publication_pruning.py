"""Disposable-Postgres coverage: catalog publication prunes older catalog versions.

After the publication transaction commits, catalog publication keeps, for each
country's model, the installed version and the most recently created other
version, and prunes every other stored version: one transaction per version
deletes its current-law parameter values, parameter tree rows and parameter
search file and records when (``catalog_values_pruned_at``). Publishing a
pruned version again restores those rows from the installed packages.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.catalog import publication as publication_module
from policyengine_api.data.v2.catalog.publication import publish_catalog
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPruningFailure,
    PrunedCatalogVersion,
)
from policyengine_api.data.v2.database import build_v2_read_session_factory
from policyengine_api.data.v2.models import (
    Dynamic,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.privileges import CATALOG_WRITER_ROLE
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.v2.metadata.response_cache_support import (
    MetadataResponseCache,
)
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.metadata.database_session import (
    MetadataDatabaseSession,
)
from policyengine_api.services.v2.metadata.process_state import (
    SelectedCatalogStore,
)
from policyengine_api.services.v2.metadata.services import V2MetadataService
from tests.fixtures.v2_catalog import normalized_catalog

REPO = Path(__file__).parents[2]
DISPOSABLE_DATABASE = "policyengine_v2_alembic_test"
OLD_VERSION = "5.0.1"
PREVIOUS_VERSION = "5.0.2"
INSTALLED_VERSION = "5.0.3"
US_MODEL = "policyengine-us"
UK_MODEL = "policyengine-uk"
MODEL_NAMES = (US_MODEL, UK_MODEL)
PROBE_DYNAMIC_NAME = "catalog-pruning-probe"
# Each fixture catalog version holds, per country, two current-law values,
# three parameter tree rows and one search file.
FIXTURE_PRUNED_ROWS = {"parameter_values": 2, "tree_rows": 3, "search_files": 1}
# The tables pruning never changes, read per catalog version.
VERSIONED_TABLES = ("variables", "parameter_nodes", "parameters", "datasets", "regions")


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
        pytest.fail("catalog pruning tests require disposable local Postgres")
    return database_url


def _clear_catalog(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
        connection.execute(
            text("DELETE FROM dynamics WHERE name = :name"),
            {"name": PROBE_DYNAMIC_NAME},
        )


@pytest.fixture
def publication_engine() -> Engine:
    database_url = _disposable_url()
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(database_url, poolclass=NullPool)
    _clear_catalog(engine)
    yield engine
    _clear_catalog(engine)
    engine.dispose()


def _publish(engine: Engine, version: str):
    return publish_catalog(engine, normalized_catalog(policyengine_version=version))


def _version_id(engine: Engine, model_name: str, version: str) -> UUID:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT version.id FROM tax_benefit_model_versions AS version "
                "JOIN tax_benefit_models AS model ON model.id = version.model_id "
                "WHERE model.name = :model_name AND version.version = :version"
            ),
            {"model_name": model_name, "version": version},
        ).scalar_one()


def _pruned_at(engine: Engine, model_name: str, version: str) -> datetime | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT catalog_values_pruned_at FROM tax_benefit_model_versions "
                "WHERE id = :version_id"
            ),
            {"version_id": _version_id(engine, model_name, version)},
        ).scalar_one()


def _rows(engine: Engine, statement: str, version_id: UUID) -> list[tuple]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(text(statement), {"version_id": version_id})
        ]


def _prunable_rows(engine: Engine, model_name: str, version: str) -> dict:
    """Return what pruning deletes from one stored version, in a stable order.

    Tree rows leave out their random IDs and creation times, which differ
    between any two publications.
    """
    version_id = _version_id(engine, model_name, version)
    return {
        "parameter_values": _rows(
            engine,
            "SELECT value.id, value.parameter_id, value.value_json::text, "
            "value.start_date, value.end_date FROM parameter_values AS value "
            "JOIN parameters AS parameter ON parameter.id = value.parameter_id "
            "WHERE parameter.tax_benefit_model_version_id = :version_id "
            "AND value.policy_id IS NULL AND value.dynamic_id IS NULL "
            "ORDER BY value.id",
            version_id,
        ),
        "tree_rows": _rows(
            engine,
            "SELECT parent_path, path, position, label, child_type, child_count, "
            "reform_position, reform_child_count, parameter_id, economy, household "
            "FROM parameter_tree_children "
            "WHERE tax_benefit_model_version_id = :version_id ORDER BY path",
            version_id,
        ),
        "search_files": _rows(
            engine,
            "SELECT file_format, compressed_content, content_sha256, "
            "uncompressed_size, compressed_size FROM parameter_search_files "
            "WHERE tax_benefit_model_version_id = :version_id ORDER BY file_format",
            version_id,
        ),
    }


def _kept_rows(engine: Engine, model_name: str, version: str) -> dict:
    """Return every row of one stored version that pruning never changes."""
    version_id = _version_id(engine, model_name, version)
    kept = {
        table_name: _rows(
            engine,
            f"SELECT * FROM {table_name} "
            "WHERE tax_benefit_model_version_id = :version_id ORDER BY id",
            version_id,
        )
        for table_name in VERSIONED_TABLES
    }
    kept["tax_benefit_model_versions"] = _rows(
        engine,
        "SELECT id, created_at, model_id, version, description, current_law_id, "
        "metadata_time_periods::text, catalog_format, entities::text, "
        "basic_inputs::text FROM tax_benefit_model_versions WHERE id = :version_id",
        version_id,
    )
    return kept


def _owned_rows(engine: Engine) -> dict[str, list[tuple]]:
    """Return every policy, dynamic and value a policy or dynamic owns."""
    with engine.connect() as connection:
        return {
            "owned_values": [
                tuple(row)
                for row in connection.execute(
                    text(
                        "SELECT id, created_at, parameter_id, value_json::text, "
                        "start_date, end_date, policy_id, dynamic_id "
                        "FROM parameter_values "
                        "WHERE policy_id IS NOT NULL OR dynamic_id IS NOT NULL "
                        "ORDER BY id"
                    )
                )
            ],
            "policies": [
                tuple(row)
                for row in connection.execute(
                    text("SELECT * FROM policies ORDER BY id")
                )
            ],
            "dynamics": [
                tuple(row)
                for row in connection.execute(
                    text("SELECT * FROM dynamics ORDER BY id")
                )
            ],
        }


def _add_saved_reform_and_dynamic(engine: Engine, version: str) -> None:
    """Store a policy and a dynamic, each with its own value of a US parameter."""
    with Session(engine) as session:
        model = session.exec(
            select(TaxBenefitModel).where(TaxBenefitModel.name == US_MODEL)
        ).one()
        model_version = session.exec(
            select(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.model_id == model.id,
                TaxBenefitModelVersion.version == version,
            )
        ).one()
        parameter = session.exec(
            select(Parameter).where(
                Parameter.tax_benefit_model_version_id == model_version.id,
                Parameter.name == "gov.example.rate",
            )
        ).one()
        policy = Policy(
            country_id="us",
            tax_benefit_model_id=model.id,
            tax_benefit_model_version_id=model_version.id,
            canonicalization_version=1,
            content_hash=uuid4().hex * 2,
        )
        dynamic = Dynamic(name=PROBE_DYNAMIC_NAME)
        session.add_all([policy, dynamic])
        session.flush()
        session.add_all(
            [
                ParameterValue(
                    parameter_id=parameter.id,
                    value_json=0.5,
                    start_date=datetime(2026, 1, 1, tzinfo=UTC),
                    policy_id=policy.id,
                ),
                ParameterValue(
                    parameter_id=parameter.id,
                    value_json=0.3,
                    start_date=datetime(2026, 1, 1, tzinfo=UTC),
                    dynamic_id=dynamic.id,
                ),
            ]
        )
        session.commit()


def _fixture_pruned(country_id: str, version: str) -> PrunedCatalogVersion:
    return PrunedCatalogVersion(
        country_id=country_id,
        policyengine_version=version,
        parameter_values=FIXTURE_PRUNED_ROWS["parameter_values"],
        parameter_tree_children=FIXTURE_PRUNED_ROWS["tree_rows"],
        parameter_search_files=FIXTURE_PRUNED_ROWS["search_files"],
    )


def test_publication_prunes_versions_before_the_previous_release_as_the_writer(
    publication_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """Pruning deletes exactly the old version's current-law data, as the writer.

    The old version holds a saved reform and a dynamic, each with its own
    value. Only the old version's current-law values, tree rows and search
    file go; its marker is set. The kept versions, the reform, the dynamic,
    their values, the old version's parameters and every other row stay.
    """
    writer_engine = v2_engine_as_role(CATALOG_WRITER_ROLE, poolclass=NullPool)
    try:
        _publish(writer_engine, OLD_VERSION)
        _add_saved_reform_and_dynamic(publication_engine, OLD_VERSION)
        second = _publish(writer_engine, PREVIOUS_VERSION)
        before = {
            (model_name, version): (
                _kept_rows(publication_engine, model_name, version),
                _prunable_rows(publication_engine, model_name, version),
            )
            for model_name in MODEL_NAMES
            for version in (OLD_VERSION, PREVIOUS_VERSION)
        }
        owned_before = _owned_rows(publication_engine)

        third = _publish(writer_engine, INSTALLED_VERSION)
    finally:
        writer_engine.dispose()

    assert second.pruned_catalog_versions == ()
    assert third.pruned_catalog_versions == (
        _fixture_pruned("uk", OLD_VERSION),
        _fixture_pruned("us", OLD_VERSION),
    )
    assert third.catalog_pruning_failures == ()
    assert len(owned_before["owned_values"]) == 2
    assert _owned_rows(publication_engine) == owned_before
    for model_name in MODEL_NAMES:
        old_kept, old_prunable = before[(model_name, OLD_VERSION)]
        assert all(old_prunable.values()), model_name
        assert _kept_rows(publication_engine, model_name, OLD_VERSION) == old_kept
        assert _prunable_rows(publication_engine, model_name, OLD_VERSION) == {
            "parameter_values": [],
            "tree_rows": [],
            "search_files": [],
        }
        assert _pruned_at(publication_engine, model_name, OLD_VERSION) is not None
        assert (
            _kept_rows(publication_engine, model_name, PREVIOUS_VERSION),
            _prunable_rows(publication_engine, model_name, PREVIOUS_VERSION),
        ) == before[(model_name, PREVIOUS_VERSION)]
        for version in (PREVIOUS_VERSION, INSTALLED_VERSION):
            assert _pruned_at(publication_engine, model_name, version) is None
        installed = _prunable_rows(publication_engine, model_name, INSTALLED_VERSION)
        assert {name: len(rows) for name, rows in installed.items()} == (
            FIXTURE_PRUNED_ROWS
        )


def test_republishing_a_pruned_version_restores_what_its_publication_wrote(
    publication_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """A rollback that installs a pruned version restores its rows and marker.

    The restored current-law values, tree rows and search file equal those
    the version's own first publication wrote. The rollback then keeps the
    installed version and the most recently created other one, so it prunes
    the version in between.
    """
    writer_engine = v2_engine_as_role(CATALOG_WRITER_ROLE, poolclass=NullPool)
    try:
        _publish(writer_engine, OLD_VERSION)
        first_published = {
            model_name: _prunable_rows(publication_engine, model_name, OLD_VERSION)
            for model_name in MODEL_NAMES
        }
        _publish(writer_engine, PREVIOUS_VERSION)
        _publish(writer_engine, INSTALLED_VERSION)
        assert all(
            _pruned_at(publication_engine, model_name, OLD_VERSION) is not None
            for model_name in MODEL_NAMES
        )

        rollback = _publish(writer_engine, OLD_VERSION)
        again = _publish(writer_engine, OLD_VERSION)
    finally:
        writer_engine.dispose()

    for model_name in MODEL_NAMES:
        assert (
            _prunable_rows(publication_engine, model_name, OLD_VERSION)
            == first_published[model_name]
        )
        assert _pruned_at(publication_engine, model_name, OLD_VERSION) is None
        assert _pruned_at(publication_engine, model_name, PREVIOUS_VERSION) is not None
        assert _pruned_at(publication_engine, model_name, INSTALLED_VERSION) is None
    assert rollback.restored_catalog_versions == (
        ("us", OLD_VERSION, FIXTURE_PRUNED_ROWS["parameter_values"]),
        ("uk", OLD_VERSION, FIXTURE_PRUNED_ROWS["parameter_values"]),
    )
    assert rollback.parameter_trees_written == (
        (UK_MODEL, OLD_VERSION, FIXTURE_PRUNED_ROWS["tree_rows"]),
        (US_MODEL, OLD_VERSION, FIXTURE_PRUNED_ROWS["tree_rows"]),
    )
    assert [
        (model_name, version)
        for model_name, version, *_sizes in rollback.parameter_search_files_written
    ] == [(UK_MODEL, OLD_VERSION), (US_MODEL, OLD_VERSION)]
    assert rollback.pruned_catalog_versions == (
        _fixture_pruned("uk", PREVIOUS_VERSION),
        _fixture_pruned("us", PREVIOUS_VERSION),
    )
    assert rollback.as_dict()["restored_catalog_versions"] == [
        {
            "country_id": "us",
            "policyengine_version": OLD_VERSION,
            "parameter_values": FIXTURE_PRUNED_ROWS["parameter_values"],
        },
        {
            "country_id": "uk",
            "policyengine_version": OLD_VERSION,
            "parameter_values": FIXTURE_PRUNED_ROWS["parameter_values"],
        },
    ]
    assert again.restored_catalog_versions == ()
    assert again.pruned_catalog_versions == ()


def test_a_pruning_failure_rolls_back_that_version_and_publication_succeeds(
    publication_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One version's failure leaves it unchanged; the others are still pruned.

    The failure comes after that version's deletes and marker, in the same
    transaction, so all of them roll back. Publication still returns its
    evidence, which reports the failure, and the next run prunes the version.
    """
    _publish(publication_engine, OLD_VERSION)
    _publish(publication_engine, PREVIOUS_VERSION)
    failing_version_id = _version_id(publication_engine, US_MODEL, OLD_VERSION)
    us_old_before = _prunable_rows(publication_engine, US_MODEL, OLD_VERSION)
    prune_catalog_version = publication_module.prune_catalog_version

    def prune_then_fail_for_one_version(connection, version_id):
        deleted = prune_catalog_version(connection, version_id)
        if version_id == failing_version_id:
            connection.execute(text("SELECT 1 / 0"))
        return deleted

    monkeypatch.setattr(
        publication_module, "prune_catalog_version", prune_then_fail_for_one_version
    )
    evidence = _publish(publication_engine, INSTALLED_VERSION)
    monkeypatch.undo()

    expected_failure = CatalogPruningFailure(
        country_id="us",
        policyengine_version=OLD_VERSION,
        error_type="DataError",
        message=(
            f"pruning the us catalog version {OLD_VERSION} failed and was rolled "
            "back: the database reported DivisionByZero (SQLSTATE 22012)"
        ),
    )
    assert evidence.catalog_pruning_failures == (expected_failure,)
    assert evidence.as_dict()["catalog_pruning_failures"] == [
        {
            "country_id": "us",
            "policyengine_version": OLD_VERSION,
            "error_type": "DataError",
            "message": expected_failure.message,
        }
    ]
    assert evidence.pruned_catalog_versions == (_fixture_pruned("uk", OLD_VERSION),)
    assert _prunable_rows(publication_engine, US_MODEL, OLD_VERSION) == us_old_before
    assert _pruned_at(publication_engine, US_MODEL, OLD_VERSION) is None
    assert _pruned_at(publication_engine, UK_MODEL, OLD_VERSION) is not None
    assert _version_id(publication_engine, US_MODEL, INSTALLED_VERSION) is not None

    retried = _publish(publication_engine, INSTALLED_VERSION)

    assert retried.pruned_catalog_versions == (_fixture_pruned("us", OLD_VERSION),)
    assert retried.catalog_pruning_failures == ()


def test_a_failure_to_read_the_stored_versions_is_reported_and_publication_succeeds(
    publication_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database error choosing the versions to prune doesn't fail publication.

    The read of the stored versions runs after the publication committed. Its
    failure prunes nothing and is reported for each country of the catalog,
    without a version, since none was chosen; the next run prunes them.
    """
    _publish(publication_engine, OLD_VERSION)
    _publish(publication_engine, PREVIOUS_VERSION)

    def fail_to_read_stored_versions(connection, model_names):
        connection.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(
        publication_module,
        "read_stored_catalog_versions",
        fail_to_read_stored_versions,
    )
    evidence = _publish(publication_engine, INSTALLED_VERSION)
    monkeypatch.undo()

    assert evidence.pruned_catalog_versions == ()
    assert evidence.catalog_pruning_failures == tuple(
        CatalogPruningFailure(
            country_id=country_id,
            policyengine_version=None,
            error_type="DataError",
            message=(
                f"reading the stored {country_id} catalog versions to choose "
                "which to prune failed: the database reported DivisionByZero "
                "(SQLSTATE 22012)"
            ),
        )
        for country_id in ("uk", "us")
    )
    assert [
        failure["policyengine_version"]
        for failure in evidence.as_dict()["catalog_pruning_failures"]
    ] == [None, None]
    for model_name in MODEL_NAMES:
        assert _version_id(publication_engine, model_name, INSTALLED_VERSION)
        assert _pruned_at(publication_engine, model_name, OLD_VERSION) is None

    retried = _publish(publication_engine, INSTALLED_VERSION)

    assert retried.pruned_catalog_versions == (
        _fixture_pruned("uk", OLD_VERSION),
        _fixture_pruned("us", OLD_VERSION),
    )
    assert retried.catalog_pruning_failures == ()


def _route_client(dependencies: NativeRouteDependencies) -> TestClient:
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        )
    )


def _runtime_client(engine: Engine, **reader_options) -> TestClient:
    """Serve the metadata routes from ``engine`` with the installed version running."""
    read_sessions = build_v2_read_session_factory(engine)
    selected_catalogs = reader_options.get("selected_catalogs")
    return _route_client(
        NativeRouteDependencies(
            readiness_probe=lambda: True,
            gateway_client_factory=lambda: None,
            metadata_reader_factory=lambda: None,
            v2_metadata_reader_factory=lambda: V2MetadataService(
                MetadataDatabaseSession(read_sessions()),
                running_policyengine_version=INSTALLED_VERSION,
                selected_catalogs=selected_catalogs,
            ),
            v2_metadata_response_cache=reader_options.get("response_cache"),
        )
    )


def _pruned_message(country_id: str, version: str) -> str:
    return (
        f"PolicyEngine.py {version}'s current-law parameter values for "
        f"{country_id} were removed from the catalog, with its parameter tree and "
        f"search file; they return when PolicyEngine.py {version} is installed again"
    )


def test_routes_answer_503_for_a_pruned_version_and_serve_its_kept_rows(
    publication_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """Read as the Public API's runtime role, with its declared privileges."""
    for version in (OLD_VERSION, PREVIOUS_VERSION, INSTALLED_VERSION):
        _publish(publication_engine, version)
    old_catalog = normalized_catalog(policyengine_version=OLD_VERSION).country("us")
    old_query = {"country_id": "us", "policyengine_version": OLD_VERSION}
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    try:
        client = _runtime_client(runtime_engine)
        pruned_responses = {
            label: client.get(path, params=params, headers=headers)
            for label, path, params, headers in (
                ("values", "/v2/parameter-values", old_query, {}),
                (
                    "one value",
                    f"/v2/parameter-values/{old_catalog.parameters[0].values[0].id}",
                    old_query,
                    {},
                ),
                ("tree", "/v2/parameters/children", old_query, {}),
                ("search file", "/v2/parameters/search-file", old_query, {}),
                (
                    "search file revalidation",
                    "/v2/parameters/search-file",
                    old_query,
                    {"If-None-Match": '"0123"'},
                ),
                ("variables", "/v2/model-catalog/variables", old_query, {}),
                (
                    "parameters",
                    "/v2/model-catalog/parameters",
                    {**old_query, "name": "gov.example.rate"},
                    {},
                ),
            )
        }
        kept_responses = {
            path: client.get(path, params=old_query)
            for path in (
                "/v2/parameters",
                f"/v2/parameters/{old_catalog.parameters[0].id}",
                "/v2/variables",
                "/v2/model-catalog",
                "/v2/regions",
                "/v2/datasets",
                "/v2/economy-options",
                "/v2/tax-benefit-model-versions",
            )
        }
        previous_values = client.get(
            "/v2/parameter-values",
            params={"country_id": "us", "policyengine_version": PREVIOUS_VERSION},
        )
    finally:
        runtime_engine.dispose()

    for label, response in pruned_responses.items():
        assert response.status_code == 503, label
        assert response.json() == {
            "status": "error",
            "message": _pruned_message("us", OLD_VERSION),
        }, label
        assert response.headers["cache-control"] == "no-store", label
    for path, response in kept_responses.items():
        assert response.status_code == 200, (path, response.text)
    assert len(previous_values.json()["result"]["items"]) == 2


def test_a_process_that_selected_a_version_before_its_pruning_answers_503(
    publication_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """The production reader keeps selections and whole-version responses.

    A process of the previous release selected the old version before the
    next release's publication pruned it. Its later requests read the marker
    again when they find no values, so they answer 503 rather than an empty
    result that a cache could keep for a day.
    """
    _publish(publication_engine, OLD_VERSION)
    _publish(publication_engine, PREVIOUS_VERSION)
    old_query = {"country_id": "us", "policyengine_version": OLD_VERSION}
    selected_catalogs = SelectedCatalogStore()
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    try:
        client = _runtime_client(
            runtime_engine,
            selected_catalogs=selected_catalogs,
            response_cache=MetadataResponseCache(),
        )
        before_pruning = client.get("/v2/parameter-values", params=old_query)
        _publish(publication_engine, INSTALLED_VERSION)
        after_pruning = {
            path: client.get(path, params=old_query)
            for path in (
                "/v2/parameter-values",
                "/v2/parameters/children",
                "/v2/parameters/search-file",
            )
        }
    finally:
        runtime_engine.dispose()

    assert before_pruning.status_code == 200
    assert len(before_pruning.json()["result"]["items"]) == 2
    kept_selection = selected_catalogs.get(("us", OLD_VERSION))
    assert kept_selection is not None
    assert kept_selection.model_version.catalog_values_pruned_at is None
    for path, response in after_pruning.items():
        assert response.status_code == 503, path
        assert response.json()["message"] == _pruned_message("us", OLD_VERSION)
        assert response.headers["cache-control"] == "no-store", path
