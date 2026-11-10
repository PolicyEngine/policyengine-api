"""Disposable-Postgres coverage: catalog publication prunes older catalog versions.

After the publication transaction commits, catalog publication keeps, for each
country's model, the installed version and the two most recently published
other versions, and prunes every other stored version: one transaction per version
deletes its current-law parameter values, parameter tree rows and parameter
search file and records when (``catalog_values_pruned_at``). Publishing a
pruned version again restores those rows from the installed packages.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
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
from policyengine_api.data.v2.catalog.publication_pruning import (
    read_stored_catalog_versions,
)
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
# The earlier of the two other versions pruning keeps, with the previous one.
EARLIER_KEPT_VERSION = "5.0.2"
PREVIOUS_VERSION = "5.0.3"
INSTALLED_VERSION = "5.0.4"
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


def test_publication_prunes_versions_older_than_the_kept_ones_as_the_writer(
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
        _publish(writer_engine, EARLIER_KEPT_VERSION)
        second = _publish(writer_engine, PREVIOUS_VERSION)
        before = {
            (model_name, version): (
                _kept_rows(publication_engine, model_name, version),
                _prunable_rows(publication_engine, model_name, version),
            )
            for model_name in MODEL_NAMES
            for version in (OLD_VERSION, EARLIER_KEPT_VERSION, PREVIOUS_VERSION)
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
        for version in (EARLIER_KEPT_VERSION, PREVIOUS_VERSION):
            assert (
                _kept_rows(publication_engine, model_name, version),
                _prunable_rows(publication_engine, model_name, version),
            ) == before[(model_name, version)]
        for version in (EARLIER_KEPT_VERSION, PREVIOUS_VERSION, INSTALLED_VERSION):
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
    installed version and the two most recently published other ones, so it
    prunes the earliest of the versions released after it.
    """
    writer_engine = v2_engine_as_role(CATALOG_WRITER_ROLE, poolclass=NullPool)
    try:
        _publish(writer_engine, OLD_VERSION)
        first_published = {
            model_name: _prunable_rows(publication_engine, model_name, OLD_VERSION)
            for model_name in MODEL_NAMES
        }
        _publish(writer_engine, EARLIER_KEPT_VERSION)
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
        assert (
            _pruned_at(publication_engine, model_name, EARLIER_KEPT_VERSION) is not None
        )
        for version in (PREVIOUS_VERSION, INSTALLED_VERSION):
            assert _pruned_at(publication_engine, model_name, version) is None
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
        _fixture_pruned("uk", EARLIER_KEPT_VERSION),
        _fixture_pruned("us", EARLIER_KEPT_VERSION),
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
    _publish(publication_engine, EARLIER_KEPT_VERSION)
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
    _publish(publication_engine, EARLIER_KEPT_VERSION)
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


def test_routes_answer_404_for_a_pruned_version_and_serve_its_kept_rows(
    publication_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """Read as the Public API's runtime role, with its declared privileges."""
    for version in (
        OLD_VERSION,
        EARLIER_KEPT_VERSION,
        PREVIOUS_VERSION,
        INSTALLED_VERSION,
    ):
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
        assert response.status_code == 404, label
        assert response.json() == {
            "status": "error",
            "message": _pruned_message("us", OLD_VERSION),
        }, label
        assert response.headers["cache-control"] == "no-store", label
    for path, response in kept_responses.items():
        assert response.status_code == 200, (path, response.text)
    assert len(previous_values.json()["result"]["items"]) == 2


def test_a_process_that_selected_a_version_before_its_pruning_answers_404(
    publication_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """The production reader keeps selections and whole-version responses.

    A process of the previous release selected the old version before the
    next release's publication pruned it. Its later requests read the marker
    again when they find no values, so they answer 404 rather than an empty
    result that a cache could keep for a day. The variables catalog body it
    built before the pruning stays kept: it answers 200 with that body, and
    304 to its ETag, which equal what restoring the version writes.
    """
    _publish(publication_engine, OLD_VERSION)
    _publish(publication_engine, EARLIER_KEPT_VERSION)
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
        variables_before_pruning = client.get(
            "/v2/model-catalog/variables", params=old_query
        )
        _publish(publication_engine, INSTALLED_VERSION)
        variables_after_pruning = client.get(
            "/v2/model-catalog/variables", params=old_query
        )
        variables_revalidated = client.get(
            "/v2/model-catalog/variables",
            params=old_query,
            headers={"If-None-Match": variables_before_pruning.headers["etag"]},
        )
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
        assert response.status_code == 404, path
        assert response.json()["message"] == _pruned_message("us", OLD_VERSION)
        assert response.headers["cache-control"] == "no-store", path
    assert variables_before_pruning.status_code == 200
    assert variables_after_pruning.status_code == 200
    assert variables_after_pruning.content == variables_before_pruning.content
    assert (
        variables_after_pruning.headers["etag"]
        == variables_before_pruning.headers["etag"]
    )
    assert variables_revalidated.status_code == 304


def test_a_process_that_selected_a_pruned_version_serves_it_once_restored(
    publication_engine: Engine,
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    """A selection kept while the version was pruned doesn't outlive restoration.

    A process selected the old version while it was pruned and answered 404.
    A rollback's publication then restores it, and the same process serves
    its values, tree and search file again.
    """
    for version in (
        OLD_VERSION,
        EARLIER_KEPT_VERSION,
        PREVIOUS_VERSION,
        INSTALLED_VERSION,
    ):
        _publish(publication_engine, version)
    old_query = {"country_id": "us", "policyengine_version": OLD_VERSION}
    selected_catalogs = SelectedCatalogStore()
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    try:
        client = _runtime_client(
            runtime_engine,
            selected_catalogs=selected_catalogs,
            response_cache=MetadataResponseCache(),
        )
        while_pruned = client.get("/v2/parameter-values", params=old_query)
        _publish(publication_engine, OLD_VERSION)
        after_restoration = {
            path: client.get(path, params=old_query)
            for path in (
                "/v2/parameter-values",
                "/v2/parameters/children",
                "/v2/parameters/search-file",
            )
        }
    finally:
        runtime_engine.dispose()

    assert while_pruned.status_code == 404
    for path, response in after_restoration.items():
        assert response.status_code == 200, (path, response.text)
    values = after_restoration["/v2/parameter-values"].json()["result"]["items"]
    assert len(values) == 2
    kept_selection = selected_catalogs.get(("us", OLD_VERSION))
    assert kept_selection is not None
    assert kept_selection.model_version.catalog_values_pruned_at is None


def test_a_version_kept_by_the_time_its_transaction_runs_is_not_pruned(
    publication_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each pruning transaction chooses again, under the publication lock.

    Between the read that chose the old US version and its transaction, a
    publication that republished it commits, so the rule keeps it: its
    ``catalog_last_published_at`` becomes the latest of the versions other than
    the installed one, as that publication sets it. Its transaction then skips
    it, and nothing reports it as pruned or failed.
    """
    _publish(publication_engine, OLD_VERSION)
    _publish(publication_engine, EARLIER_KEPT_VERSION)
    _publish(publication_engine, PREVIOUS_VERSION)
    kept_meanwhile = _version_id(publication_engine, US_MODEL, OLD_VERSION)
    us_old_before = _prunable_rows(publication_engine, US_MODEL, OLD_VERSION)
    read_stored_catalog_versions = publication_module.read_stored_catalog_versions
    reads: list[str] = []

    def read_then_change_the_stored_versions(connection, model_names):
        stored_versions = read_stored_catalog_versions(connection, model_names)
        if not reads:
            with publication_engine.begin() as other_publisher:
                other_publisher.execute(
                    text(
                        "UPDATE tax_benefit_model_versions "
                        "SET catalog_last_published_at = now() + interval '1 day' "
                        "WHERE id = :version_id"
                    ),
                    {"version_id": kept_meanwhile},
                )
        reads.append("read")
        return stored_versions

    monkeypatch.setattr(
        publication_module,
        "read_stored_catalog_versions",
        read_then_change_the_stored_versions,
    )
    evidence = _publish(publication_engine, INSTALLED_VERSION)
    monkeypatch.undo()

    assert evidence.pruned_catalog_versions == (_fixture_pruned("uk", OLD_VERSION),)
    assert evidence.catalog_pruning_failures == ()
    assert _prunable_rows(publication_engine, US_MODEL, OLD_VERSION) == us_old_before
    assert _pruned_at(publication_engine, US_MODEL, OLD_VERSION) is None
    # The rule now chooses the US 5.0.2, which this run's first choice didn't.
    assert _pruned_at(publication_engine, US_MODEL, EARLIER_KEPT_VERSION) is None


def test_a_non_database_error_rolls_back_that_version_and_publication_succeeds(
    publication_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any exception pruning one version is reported, not only a database error.

    It comes after that version's deletes and marker, so they roll back; the
    other version is still pruned and publication returns its evidence.
    """
    _publish(publication_engine, OLD_VERSION)
    _publish(publication_engine, EARLIER_KEPT_VERSION)
    _publish(publication_engine, PREVIOUS_VERSION)
    failing_version_id = _version_id(publication_engine, US_MODEL, OLD_VERSION)
    us_old_before = _prunable_rows(publication_engine, US_MODEL, OLD_VERSION)
    prune_catalog_version = publication_module.prune_catalog_version

    def prune_then_raise_for_one_version(connection, version_id):
        deleted = prune_catalog_version(connection, version_id)
        if version_id == failing_version_id:
            missing_name = "gov.example.rate"
            raise KeyError(missing_name)
        return deleted

    monkeypatch.setattr(
        publication_module, "prune_catalog_version", prune_then_raise_for_one_version
    )
    evidence = _publish(publication_engine, INSTALLED_VERSION)
    monkeypatch.undo()

    assert evidence.catalog_pruning_failures == (
        CatalogPruningFailure(
            country_id="us",
            policyengine_version=OLD_VERSION,
            error_type="KeyError",
            message=(
                f"pruning the us catalog version {OLD_VERSION} failed and was "
                "rolled back: it raised KeyError"
            ),
        ),
    )
    assert evidence.pruned_catalog_versions == (_fixture_pruned("uk", OLD_VERSION),)
    assert _prunable_rows(publication_engine, US_MODEL, OLD_VERSION) == us_old_before
    assert _pruned_at(publication_engine, US_MODEL, OLD_VERSION) is None


def test_a_run_prunes_at_most_two_versions_and_the_next_run_the_rest(
    publication_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first run after many releases prunes the two oldest versions only.

    Four versions are chosen (5.0.1 and 5.0.2, in both countries; 5.0.3 and
    5.0.4 are kept). The first run prunes both countries' 5.0.1 and reports
    two left; the next prunes the rest.
    """
    monkeypatch.setattr(
        publication_module,
        "catalog_versions_to_prune",
        lambda stored_versions, installed_versions: (),
    )
    for version in ("5.0.1", "5.0.2", "5.0.3", "5.0.4"):
        _publish(publication_engine, version)
    monkeypatch.undo()

    first = _publish(publication_engine, "5.0.5")
    second = _publish(publication_engine, "5.0.5")
    third = _publish(publication_engine, "5.0.5")

    assert first.pruned_catalog_versions == (
        _fixture_pruned("uk", "5.0.1"),
        _fixture_pruned("us", "5.0.1"),
    )
    assert first.as_dict()["catalog_versions_left_to_prune"] == 2
    assert second.pruned_catalog_versions == (
        _fixture_pruned("uk", "5.0.2"),
        _fixture_pruned("us", "5.0.2"),
    )
    assert second.as_dict()["catalog_versions_left_to_prune"] == 0
    assert third.pruned_catalog_versions == ()
    for model_name in MODEL_NAMES:
        for kept_version in ("5.0.3", "5.0.4"):
            assert _pruned_at(publication_engine, model_name, kept_version) is None


def test_a_version_without_current_law_rows_is_marked_pruned_with_zero_counts(
    publication_engine: Engine,
) -> None:
    """Pruning a version that holds none of the rows it deletes still marks it."""
    _publish(publication_engine, OLD_VERSION)
    us_old_id = _version_id(publication_engine, US_MODEL, OLD_VERSION)
    with publication_engine.begin() as connection:
        for statement in (
            "DELETE FROM parameter_values WHERE policy_id IS NULL "
            "AND dynamic_id IS NULL AND parameter_id IN (SELECT id FROM parameters "
            "WHERE tax_benefit_model_version_id = :version_id)",
            "DELETE FROM parameter_tree_children "
            "WHERE tax_benefit_model_version_id = :version_id",
            "DELETE FROM parameter_search_files "
            "WHERE tax_benefit_model_version_id = :version_id",
        ):
            connection.execute(text(statement), {"version_id": us_old_id})
    _publish(publication_engine, EARLIER_KEPT_VERSION)
    _publish(publication_engine, PREVIOUS_VERSION)

    evidence = _publish(publication_engine, INSTALLED_VERSION)

    assert evidence.pruned_catalog_versions == (
        _fixture_pruned("uk", OLD_VERSION),
        PrunedCatalogVersion(
            country_id="us",
            policyengine_version=OLD_VERSION,
            parameter_values=0,
            parameter_tree_children=0,
            parameter_search_files=0,
        ),
    )
    assert evidence.catalog_pruning_failures == ()
    assert _pruned_at(publication_engine, US_MODEL, OLD_VERSION) is not None


def _last_published_at(engine: Engine, model_name: str, version: str) -> datetime:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT catalog_last_published_at FROM tax_benefit_model_versions "
                "WHERE id = :version_id"
            ),
            {"version_id": _version_id(engine, model_name, version)},
        ).scalar_one()


def test_every_publication_records_when_it_published_the_version(
    publication_engine: Engine,
) -> None:
    """A new version, a republish with no change and a restoring one all record it.

    Each publication sets ``catalog_last_published_at`` of the versions it
    publishes, in its own transaction, and no other version's. Pruning leaves
    it as it was.
    """
    _publish(publication_engine, OLD_VERSION)
    first = {
        model_name: _last_published_at(publication_engine, model_name, OLD_VERSION)
        for model_name in MODEL_NAMES
    }
    _publish(publication_engine, OLD_VERSION)
    unchanged_republish = {
        model_name: _last_published_at(publication_engine, model_name, OLD_VERSION)
        for model_name in MODEL_NAMES
    }
    for version in (EARLIER_KEPT_VERSION, PREVIOUS_VERSION, INSTALLED_VERSION):
        _publish(publication_engine, version)
    while_pruned = {
        model_name: _last_published_at(publication_engine, model_name, OLD_VERSION)
        for model_name in MODEL_NAMES
    }
    installed_before = {
        model_name: _last_published_at(
            publication_engine, model_name, INSTALLED_VERSION
        )
        for model_name in MODEL_NAMES
    }

    restoring = _publish(publication_engine, OLD_VERSION)

    assert {
        (country_id, version)
        for country_id, version, _values in restoring.restored_catalog_versions
    } == {("us", OLD_VERSION), ("uk", OLD_VERSION)}
    for model_name in MODEL_NAMES:
        assert first[model_name] is not None
        assert unchanged_republish[model_name] > first[model_name]
        assert _pruned_at(publication_engine, model_name, OLD_VERSION) is None
        assert while_pruned[model_name] == unchanged_republish[model_name]
        assert (
            _last_published_at(publication_engine, model_name, OLD_VERSION)
            > while_pruned[model_name]
        )
        assert (
            _last_published_at(publication_engine, model_name, INSTALLED_VERSION)
            == installed_before[model_name]
        )


# Waiting for the pruning thread to block is bounded so a hang fails the test.
LOCK_WAIT_LIMIT_SECONDS = 30


def _wait_until_blocked_on_an_advisory_lock_or_done(
    engine: Engine, pruning: Future
) -> None:
    """Return once ``pruning`` waits for an advisory lock, or has finished.

    The disposable database's only advisory lock is the publication lock, so
    an advisory lock that isn't granted is the pruning thread's. The sleep only
    paces the polling of ``pg_locks``; the state read decides when to return.
    """
    deadline = time.monotonic() + LOCK_WAIT_LIMIT_SECONDS
    with engine.connect() as observer:
        while not pruning.done():
            waiting = observer.execute(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE locktype = 'advisory' AND NOT granted"
                )
            ).scalar_one()
            if waiting:
                return
            if time.monotonic() > deadline:
                pytest.fail("the pruning neither waited for the lock nor finished")
            time.sleep(0.01)


def test_a_pruning_transaction_chooses_again_after_waiting_for_the_lock(
    publication_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A version another publisher keeps while pruning waits for the lock stays.

    Another connection holds the publication lock. The pruning of the old US
    version starts in a thread and waits for it. Holding the lock, the other
    connection sets the old version's publication time, as a publication of it
    does, then commits, releasing the lock. The pruning then reads the stored
    versions, finds the rule keeps the version, and deletes nothing.
    """
    monkeypatch.setattr(
        publication_module,
        "catalog_versions_to_prune",
        lambda stored_versions, installed_versions: (),
    )
    for version in (
        OLD_VERSION,
        EARLIER_KEPT_VERSION,
        PREVIOUS_VERSION,
        INSTALLED_VERSION,
    ):
        _publish(publication_engine, version)
    monkeypatch.undo()
    with publication_engine.connect() as connection:
        us_old = next(
            stored
            for stored in read_stored_catalog_versions(connection, [US_MODEL])
            if stored.version == OLD_VERSION
        )
    us_old_before = _prunable_rows(publication_engine, US_MODEL, OLD_VERSION)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with publication_engine.connect() as other_publisher, other_publisher.begin():
            other_publisher.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": publication_module.PUBLICATION_ADVISORY_LOCK_KEY},
            )
            pruning = executor.submit(
                publication_module._prune_if_still_chosen,
                publication_engine,
                us_old,
                INSTALLED_VERSION,
            )
            _wait_until_blocked_on_an_advisory_lock_or_done(publication_engine, pruning)
            other_publisher.execute(
                text(
                    "UPDATE tax_benefit_model_versions "
                    "SET catalog_last_published_at = now() + interval '1 day' "
                    "WHERE id = :version_id"
                ),
                {"version_id": us_old.id},
            )
        deleted = pruning.result(timeout=LOCK_WAIT_LIMIT_SECONDS)

    assert deleted is None
    assert _pruned_at(publication_engine, US_MODEL, OLD_VERSION) is None
    assert _prunable_rows(publication_engine, US_MODEL, OLD_VERSION) == us_old_before


class _InjectedPublicationError(RuntimeError):
    """Raised by a test's checkpoint to fail a publication part way."""


def test_a_failed_republish_of_a_pruned_version_leaves_it_pruned(
    publication_engine: Engine,
) -> None:
    """Restoring is part of the publication transaction, and rolls back with it.

    The republish of the pruned version fails after it restored the values,
    wrote the tree and search file, cleared the pruning time and recorded the
    publication time. The version is then as pruning left it.
    """
    for version in (
        OLD_VERSION,
        EARLIER_KEPT_VERSION,
        PREVIOUS_VERSION,
        INSTALLED_VERSION,
    ):
        _publish(publication_engine, version)
    before = {
        model_name: (
            _prunable_rows(publication_engine, model_name, OLD_VERSION),
            _pruned_at(publication_engine, model_name, OLD_VERSION),
            _last_published_at(publication_engine, model_name, OLD_VERSION),
        )
        for model_name in MODEL_NAMES
    }
    restored_inside_the_transaction: list[int] = []

    def fail_after_restoring(stage: str, connection) -> None:
        if stage != "after_reconciliation":
            return
        restored_inside_the_transaction.append(
            connection.execute(
                text(
                    "SELECT count(*) FROM tax_benefit_model_versions "
                    "WHERE version = :version AND catalog_values_pruned_at IS NULL"
                ),
                {"version": OLD_VERSION},
            ).scalar_one()
        )
        raise _InjectedPublicationError(stage)

    with pytest.raises(_InjectedPublicationError):
        publish_catalog(
            publication_engine,
            normalized_catalog(policyengine_version=OLD_VERSION),
            checkpoint=fail_after_restoring,
        )

    assert restored_inside_the_transaction == [len(MODEL_NAMES)]
    for model_name in MODEL_NAMES:
        prunable_rows, pruned_at, last_published_at = before[model_name]
        assert prunable_rows == {
            "parameter_values": [],
            "tree_rows": [],
            "search_files": [],
        }
        assert pruned_at is not None
        assert (
            _prunable_rows(publication_engine, model_name, OLD_VERSION) == prunable_rows
        )
        assert _pruned_at(publication_engine, model_name, OLD_VERSION) == pruned_at
        assert (
            _last_published_at(publication_engine, model_name, OLD_VERSION)
            == last_published_at
        )


def test_restoring_a_version_stored_before_catalog_format_2_writes_values_only(
    publication_engine: Engine,
) -> None:
    """A version stored before catalog format 2 gets back only its values.

    Such a version (``catalog_format`` null) never had a parameter tree or a
    search file, and publication compares it without the format 2 fields and
    writes neither for it. Restoring it writes back its current-law values
    alone, equal to those it had.
    """
    _publish(publication_engine, OLD_VERSION)
    with publication_engine.begin() as connection:
        for model_name in MODEL_NAMES:
            version_id = _version_id(publication_engine, model_name, OLD_VERSION)
            for statement in (
                "UPDATE tax_benefit_model_versions SET catalog_format = NULL, "
                "entities = NULL, basic_inputs = NULL WHERE id = :version_id",
                "DELETE FROM parameter_tree_children "
                "WHERE tax_benefit_model_version_id = :version_id",
                "DELETE FROM parameter_search_files "
                "WHERE tax_benefit_model_version_id = :version_id",
            ):
                connection.execute(text(statement), {"version_id": version_id})
    before = {
        model_name: _prunable_rows(publication_engine, model_name, OLD_VERSION)
        for model_name in MODEL_NAMES
    }
    for version in (EARLIER_KEPT_VERSION, PREVIOUS_VERSION, INSTALLED_VERSION):
        _publish(publication_engine, version)
    assert all(
        _pruned_at(publication_engine, model_name, OLD_VERSION) is not None
        for model_name in MODEL_NAMES
    )

    restoring = _publish(publication_engine, OLD_VERSION)

    for model_name in MODEL_NAMES:
        assert before[model_name]["parameter_values"]
        assert before[model_name]["tree_rows"] == []
        assert before[model_name]["search_files"] == []
        assert (
            _prunable_rows(publication_engine, model_name, OLD_VERSION)
            == before[model_name]
        )
        assert _pruned_at(publication_engine, model_name, OLD_VERSION) is None
    assert {
        (country_id, version)
        for country_id, version, _values in restoring.restored_catalog_versions
    } == {("us", OLD_VERSION), ("uk", OLD_VERSION)}
    assert restoring.parameter_trees_written == ()
    assert restoring.parameter_search_files_written == ()
