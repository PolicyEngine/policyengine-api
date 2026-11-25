"""Disposable-Postgres coverage: publication keeps dynamic parameters apart (C1 · 50).

Catalog publication stores each version's model assumptions (US
``gov.simulation.`` and ``simulation.``, UK ``gov.simulation.`` and
``gov.dynamic.``) in ``dynamic_parameters`` and their current-law values in
``dynamic_parameter_values``, with the catalog's IDs, and every other parameter
in ``parameters`` as before. It compares, restores and prunes both, and
leaves dynamic parameters and their folders out of the policy tree and the
search file, whose format becomes 2. Each test publishes as the catalog
writer, which holds only its declared privileges.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlmodel import col

from policyengine_api.data.v2.catalog.publication import (
    CatalogPublicationError,
    publish_catalog,
)
from policyengine_api.data.v2.catalog.publication_types import PrunedCatalogVersion
from policyengine_api.data.v2.models import (
    Dynamic,
    DynamicParameter,
    DynamicParameterValue,
    Parameter,
    ParameterSearchFile,
    ParameterTreeChild,
    ParameterValue,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.privileges import (
    CATALOG_WRITER_ROLE,
    declared_privileges,
)
from policyengine_api.dynamic_parameters import (
    is_dynamic_parameter,
    is_dynamic_parameter_path,
)
from tests.fixtures import database_sessions
from tests.fixtures.integration.alembic_v2 import alembic_v2_config
from tests.fixtures.v2_catalog import (
    DYNAMIC_PARAMETER_RECORDS,
    catalog_with_dynamic_parameters,
)
from tests.integration.catalog_publication_support import (
    clear_format_2_fields,
    emptied_catalog,
)
from tests.integration.simulation_rows import add_row

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.data.v2.catalog.records import CountryCatalog
    from tests.integration.conftest import ManagedV2Roles

OLD_VERSION = "5.0.1"
EARLIER_KEPT_VERSION = "5.0.2"
PREVIOUS_VERSION = "5.0.3"
INSTALLED_VERSION = "5.0.4"
COUNTRY_IDS = ("us", "uk")
# The parent of the revision that moves dynamic parameters into their tables.
PARENT_REVISION = "d417fe8b1b17"


@pytest.fixture
def publication_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    with emptied_catalog(v2_owner_sessions) as sessions:
        yield sessions


@pytest.fixture
def writer_sessions(
    publication_sessions: sessionmaker[Session],
    managed_v2_roles: ManagedV2Roles,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> sessionmaker[Session]:
    """Session factories of the catalog writer, on the emptied catalog."""
    return v2_sessions_as_role(CATALOG_WRITER_ROLE)


def _publish(sessions: sessionmaker[Session], version: str = INSTALLED_VERSION):
    return publish_catalog(
        sessions, catalog_with_dynamic_parameters(policyengine_version=version)
    )


def _version_id(sessions: sessionmaker[Session], country_id: str, version: str) -> UUID:
    with sessions() as session:
        version_id: UUID = session.execute(
            sa.select(col(TaxBenefitModelVersion.id))
            .join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
            .where(
                col(TaxBenefitModel.name) == f"policyengine-{country_id}",
                col(TaxBenefitModelVersion.version) == version,
            )
        ).scalar_one()
    return version_id


def _parameters_by_name(
    sessions: sessionmaker[Session], model: Any, version_id: UUID
) -> dict[str, UUID]:
    with sessions() as session:
        return {
            row.name: row.id
            for row in session.execute(
                sa.select(col(model.name), col(model.id)).where(
                    col(model.tax_benefit_model_version_id) == version_id
                )
            )
        }


def _current_law_values(
    sessions: sessionmaker[Session], version_id: UUID
) -> dict[str, set[tuple]]:
    """Return each table's current-law values of one version: ID, parameter, value."""
    with sessions() as session:
        policy_values = session.execute(
            sa.select(
                col(ParameterValue.id),
                col(ParameterValue.parameter_id),
                sa.cast(col(ParameterValue.value_json), sa.Text),
            )
            .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
            .where(
                col(Parameter.tax_benefit_model_version_id) == version_id,
                col(ParameterValue.policy_id).is_(None),
                col(ParameterValue.dynamic_id).is_(None),
            )
        )
        dynamic_values = session.execute(
            sa.select(
                col(DynamicParameterValue.id),
                col(DynamicParameterValue.dynamic_parameter_id),
                sa.cast(col(DynamicParameterValue.value_json), sa.Text),
            )
            .join(
                DynamicParameter,
                col(DynamicParameter.id)
                == col(DynamicParameterValue.dynamic_parameter_id),
            )
            .where(
                col(DynamicParameter.tax_benefit_model_version_id) == version_id,
                col(DynamicParameterValue.dynamic_id).is_(None),
            )
        )
        return {
            "parameter_values": {tuple(row) for row in policy_values},
            "dynamic_parameter_values": {tuple(row) for row in dynamic_values},
        }


def _catalog_country(version: str, country_id: str) -> CountryCatalog:
    return catalog_with_dynamic_parameters(policyengine_version=version).country(
        country_id
    )


def _record_ids(country: CountryCatalog, *, dynamic: bool) -> dict[str, UUID]:
    return {
        parameter.name: parameter.id
        for parameter in country.parameters
        if is_dynamic_parameter(country.country_id, parameter.name) == dynamic
    }


def _record_value_ids(country: CountryCatalog, *, dynamic: bool) -> set[UUID]:
    return {
        value.id
        for parameter in country.parameters
        if is_dynamic_parameter(country.country_id, parameter.name) == dynamic
        for value in parameter.values
    }


def _tree_paths(sessions: sessionmaker[Session], version_id: UUID) -> set[str]:
    with sessions() as session:
        return set(
            session.scalars(
                sa.select(col(ParameterTreeChild.path)).where(
                    col(ParameterTreeChild.tax_benefit_model_version_id) == version_id
                )
            )
        )


def _search_files(
    sessions: sessionmaker[Session], version_id: UUID
) -> dict[int, dict | bytes]:
    """Return a version's stored search files by format, decoded when format 2."""
    with sessions() as session:
        rows = session.execute(
            sa.select(
                col(ParameterSearchFile.file_format),
                col(ParameterSearchFile.compressed_content),
            ).where(col(ParameterSearchFile.tax_benefit_model_version_id) == version_id)
        ).all()
    return {
        row.file_format: (
            json.loads(gzip.decompress(row.compressed_content))
            if row.file_format == 2
            else row.compressed_content
        )
        for row in rows
    }


def test_publication_stores_each_kind_of_parameter_in_its_own_table(
    publication_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
) -> None:
    evidence = _publish(writer_sessions)
    republished = _publish(writer_sessions)

    for country_id in COUNTRY_IDS:
        country = _catalog_country(INSTALLED_VERSION, country_id)
        version_id = _version_id(publication_sessions, country_id, INSTALLED_VERSION)
        assert _parameters_by_name(publication_sessions, Parameter, version_id) == (
            _record_ids(country, dynamic=False)
        )
        assert _parameters_by_name(
            publication_sessions, DynamicParameter, version_id
        ) == _record_ids(country, dynamic=True)
        assert set(_record_ids(country, dynamic=True)) == set(
            DYNAMIC_PARAMETER_RECORDS[country_id]
        )
        values = _current_law_values(publication_sessions, version_id)
        assert {row[0] for row in values["parameter_values"]} == _record_value_ids(
            country, dynamic=False
        )
        assert {row[0] for row in values["dynamic_parameter_values"]} == (
            _record_value_ids(country, dynamic=True)
        )
    counts = evidence.entity_counts
    assert counts["dynamic_parameters"] == 4
    assert counts["dynamic_parameter_values"] == 4
    assert counts["parameters"] == 2
    assert counts["parameter_values"] == 4
    assert republished.entity_counts == counts
    assert "dynamic_parameters" in republished.catalog_tables_analyzed
    assert "dynamic_parameter_values" in republished.catalog_tables_analyzed


def test_the_tree_and_search_file_hold_only_policy_parameters(
    publication_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
) -> None:
    _publish(writer_sessions)

    for country_id in COUNTRY_IDS:
        version_id = _version_id(publication_sessions, country_id, INSTALLED_VERSION)
        paths = _tree_paths(publication_sessions, version_id)
        assert "gov.example.rate" in paths
        assert not [
            path for path in paths if is_dynamic_parameter_path(country_id, path)
        ]
        files = _search_files(publication_sessions, version_id)
        assert set(files) == {2}
        search_file = files[2]
        assert isinstance(search_file, dict)
        assert search_file["format"] == 2
        listed = [
            entry["path"]
            for section in ("parameters", "other_parameters", "nodes")
            for entry in search_file[section]
        ]
        assert "gov.example.rate" in listed
        assert not [
            path for path in listed if is_dynamic_parameter_path(country_id, path)
        ]


@pytest.mark.parametrize(
    ("change", "table"),
    [
        ("label", "dynamic parameters"),
        ("value", "dynamic parameter values"),
    ],
)
def test_republication_fails_when_a_stored_dynamic_parameter_row_differs(
    publication_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
    change: str,
    table: str,
) -> None:
    _publish(writer_sessions)
    catalog = catalog_with_dynamic_parameters(policyengine_version=INSTALLED_VERSION)
    us = catalog.country("us")
    name = "simulation.marginal_tax_rate_delta"
    parameters = tuple(
        (
            parameter
            if parameter.name != name
            else (
                replace(parameter, label="Changed label")
                if change == "label"
                else replace(
                    parameter,
                    values=tuple(
                        replace(value, value_json=2_000) for value in parameter.values
                    ),
                )
            )
        )
        for parameter in us.parameters
    )
    changed = replace(
        catalog,
        countries=(replace(us, parameters=parameters), catalog.country("uk")),
    )

    with pytest.raises(CatalogPublicationError, match=f"in its {table}$"):
        publish_catalog(writer_sessions, changed)


def test_a_dynamic_s_own_values_are_not_compared_as_current_law(
    publication_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
) -> None:
    _publish(writer_sessions)
    version_id = _version_id(publication_sessions, "us", INSTALLED_VERSION)
    dynamic_parameter_ids = _parameters_by_name(
        publication_sessions, DynamicParameter, version_id
    )
    with publication_sessions.begin() as session:
        model_id = session.execute(
            sa.select(col(TaxBenefitModelVersion.model_id)).where(
                col(TaxBenefitModelVersion.id) == version_id
            )
        ).scalar_one()
        dynamic_id = uuid4()
        add_row(
            session,
            Dynamic,
            id=dynamic_id,
            country_id="us",
            tax_benefit_model_id=model_id,
            tax_benefit_model_version_id=version_id,
            canonicalization_version=1,
            content_hash="d" * 64,
        )
        first_record = catalog_with_dynamic_parameters().country("us").parameters
        add_row(
            session,
            DynamicParameterValue,
            id=uuid4(),
            dynamic_parameter_id=dynamic_parameter_ids[
                "simulation.marginal_tax_rate_delta"
            ],
            dynamic_id=dynamic_id,
            value_json=5,
            start_date=next(
                value.start_date
                for record in first_record
                if record.name == "simulation.marginal_tax_rate_delta"
                for value in record.values
            ),
        )

    republished = _publish(writer_sessions)

    assert republished.restored_catalog_versions == ()
    with publication_sessions() as session:
        owned = session.scalars(
            sa.select(col(DynamicParameterValue.value_json)).where(
                col(DynamicParameterValue.dynamic_id) == dynamic_id
            )
        ).all()
    assert owned == [5]


def _prunable_counts(sessions: sessionmaker[Session], version_id: UUID) -> dict:
    values = _current_law_values(sessions, version_id)
    return {
        "parameter_values": len(values["parameter_values"]),
        "dynamic_parameter_values": len(values["dynamic_parameter_values"]),
        "tree": len(_tree_paths(sessions, version_id)),
        "search_files": len(_search_files(sessions, version_id)),
    }


def test_pruning_deletes_both_tables_current_law_values_and_restore_rewrites_them(
    publication_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
) -> None:
    """A pruned version loses its current-law values from both tables only.

    Its dynamic parameters, and a dynamic's values on them, stay. Publishing
    the version again restores both tables' values with their catalog IDs.
    """
    _publish(writer_sessions, OLD_VERSION)
    old_ids = {
        country_id: _version_id(publication_sessions, country_id, OLD_VERSION)
        for country_id in COUNTRY_IDS
    }
    first_published = {
        country_id: _current_law_values(publication_sessions, version_id)
        for country_id, version_id in old_ids.items()
    }
    dynamic_parameters = {
        country_id: _parameters_by_name(
            publication_sessions, DynamicParameter, version_id
        )
        for country_id, version_id in old_ids.items()
    }
    for version in (EARLIER_KEPT_VERSION, PREVIOUS_VERSION):
        _publish(writer_sessions, version)

    installed = _publish(writer_sessions, INSTALLED_VERSION)

    assert installed.pruned_catalog_versions == tuple(
        PrunedCatalogVersion(
            country_id=country_id,
            policyengine_version=OLD_VERSION,
            parameter_values=2,
            dynamic_parameter_values=2,
            parameter_tree_children=3,
            parameter_search_files=1,
        )
        for country_id in ("uk", "us")
    )
    assert installed.as_dict()["pruned_catalog_versions"][0]["deleted_rows"] == {
        "parameter_values": 2,
        "dynamic_parameter_values": 2,
        "parameter_tree_children": 3,
        "parameter_search_files": 1,
    }
    for country_id, version_id in old_ids.items():
        assert _prunable_counts(publication_sessions, version_id) == {
            "parameter_values": 0,
            "dynamic_parameter_values": 0,
            "tree": 0,
            "search_files": 0,
        }
        assert (
            _parameters_by_name(publication_sessions, DynamicParameter, version_id)
            == dynamic_parameters[country_id]
        )

    rollback = _publish(writer_sessions, OLD_VERSION)

    assert rollback.restored_catalog_versions == (
        ("us", OLD_VERSION, 2, 2),
        ("uk", OLD_VERSION, 2, 2),
    )
    assert rollback.as_dict()["restored_catalog_versions"][0] == {
        "country_id": "us",
        "policyengine_version": OLD_VERSION,
        "parameter_values": 2,
        "dynamic_parameter_values": 2,
    }
    for country_id, version_id in old_ids.items():
        assert (
            _current_law_values(publication_sessions, version_id)
            == (first_published[country_id])
        )


def test_the_revision_s_round_trip_leaves_a_catalog_publication_accepts(
    publication_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
    disposable_v2_database_url: str,
    managed_v2_roles: ManagedV2Roles,
) -> None:
    """The revision classifies rows exactly as publication does.

    A downgrade moves the published dynamic parameters back into
    ``parameters``, and the upgrade moves them out again; publishing the same
    catalog then compares every row both ways and finds no difference. The
    upgrade creates the two tables again, so their grants are applied again,
    as the deploy's reconcile step does after every upgrade.
    """
    _publish(writer_sessions)
    version_ids = [
        _version_id(publication_sessions, country_id, INSTALLED_VERSION)
        for country_id in COUNTRY_IDS
    ]
    before = {
        version_id: (
            _parameters_by_name(publication_sessions, Parameter, version_id),
            _parameters_by_name(publication_sessions, DynamicParameter, version_id),
            _current_law_values(publication_sessions, version_id),
        )
        for version_id in version_ids
    }
    config = alembic_v2_config()
    try:
        command.downgrade(config, PARENT_REVISION)
    finally:
        command.upgrade(config, "head")
        database_sessions.grant_declared_v2_privileges(
            disposable_v2_database_url,
            declared_privileges(managed_v2_roles.deployment_environment),
        )

    _publish(writer_sessions)

    for version_id in version_ids:
        assert (
            _parameters_by_name(publication_sessions, Parameter, version_id),
            _parameters_by_name(publication_sessions, DynamicParameter, version_id),
            _current_law_values(publication_sessions, version_id),
        ) == before[version_id]


def test_republication_writes_format_2_beside_a_stored_format_1_file(
    publication_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
) -> None:
    """The installed version stored by an earlier release keeps its format 1 file.

    A release before C1 · 50 stored a format 1 file that lists the dynamic
    parameters, which it still serves after a rollback; publication adds the
    format 2 file without changing it.
    """
    _publish(writer_sessions)
    version_id = _version_id(publication_sessions, "us", INSTALLED_VERSION)
    earlier_file = gzip.compress(b'{"format":1}', mtime=0)
    with publication_sessions.begin() as session:
        session.execute(
            sa.delete(ParameterSearchFile).where(
                col(ParameterSearchFile.tax_benefit_model_version_id) == version_id
            )
        )
        add_row(
            session,
            ParameterSearchFile,
            id=uuid4(),
            tax_benefit_model_version_id=version_id,
            file_format=1,
            compressed_content=earlier_file,
            content_sha256="0" * 64,
            uncompressed_size=12,
            compressed_size=len(earlier_file),
        )

    evidence = _publish(writer_sessions)

    files = _search_files(publication_sessions, version_id)
    assert files[1] == earlier_file
    assert isinstance(files[2], dict)
    assert [model for model, *_sizes in evidence.parameter_search_files_written] == [
        "policyengine-us"
    ]


def test_a_version_stored_before_format_2_compares_its_dynamic_parameters_too(
    publication_sessions: sessionmaker[Session],
    writer_sessions: sessionmaker[Session],
) -> None:
    """A version stored before catalog format 2 has no flags in either table.

    Publishing it again compares both parameter tables without format 2's
    fields, so it passes, and still fails when a dynamic parameter's label
    differs.
    """
    _publish(writer_sessions)
    with publication_sessions.begin() as session:
        clear_format_2_fields(session)

    republished = _publish(writer_sessions)

    assert republished.parameter_trees_written == ()
    with publication_sessions() as session:
        flags = session.execute(
            sa.select(col(DynamicParameter.economy), col(DynamicParameter.household))
        ).all()
    assert flags
    assert {tuple(row) for row in flags} == {(None, None)}
    catalog = catalog_with_dynamic_parameters(policyengine_version=INSTALLED_VERSION)
    uk = catalog.country("uk")
    changed = replace(
        catalog,
        countries=(
            catalog.country("us"),
            replace(
                uk,
                parameters=tuple(
                    replace(parameter, label="Changed label")
                    if parameter.name == "gov.dynamic.obr_labour_supply_assumptions"
                    else parameter
                    for parameter in uk.parameters
                ),
            ),
        ),
    )
    with pytest.raises(CatalogPublicationError, match=r"in its dynamic parameters$"):
        publish_catalog(writer_sessions, changed)
