"""Focused structural tests for PostgreSQL catalog publication."""

from __future__ import annotations

import logging
import re
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import registry
from sqlalchemy.sql.elements import TextClause
from sqlmodel import Field, SQLModel

from policyengine_api.data.v2 import database
from policyengine_api.data.v2.catalog import (
    publication,
    publication_inserts,
    publication_reconciliation,
    publication_staging,
    publication_types,
)
from policyengine_api.data.v2.catalog.publication_parameter_tree import (
    catalog_parameter_tree,
)
from policyengine_api.data.v2.catalog.publication_staging_base import (
    STAGING_MODELS,
    TEMPORARY_UNTIL_COMMIT,
    StagingBase,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.migration_target import V2_ALEMBIC_HEAD_REVISION
from policyengine_api.dynamic_parameters import (
    is_dynamic_parameter,
    is_dynamic_parameter_path,
)
from tests.fixtures.v2_catalog import (
    catalog_with_dynamic_parameters,
    normalized_catalog,
)

REPO = Path(__file__).parents[3]


class FakeCopy:
    def __init__(self) -> None:
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def write_row(self, row) -> None:
        self.rows.append(row)


class FakeCursor:
    def __init__(self) -> None:
        self.statement = None
        self.copy_operation = FakeCopy()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def copy(self, statement: str) -> FakeCopy:
        self.statement = statement
        return self.copy_operation


class FakeDriverConnection:
    def __init__(self) -> None:
        self.selected_cursor = FakeCursor()

    def cursor(self) -> FakeCursor:
        return self.selected_cursor


class FakeConnection:
    """Stands in for the SQLAlchemy Connection a Session holds."""

    def __init__(self) -> None:
        self.connection = type(
            "ConnectionProxy",
            (),
            {"driver_connection": FakeDriverConnection()},
        )()


class FakeSession:
    """Stands in for the publishing Session, which hands out its Connection."""

    def __init__(self) -> None:
        self.held_connection = FakeConnection()

    def connection(self) -> FakeConnection:
        return self.held_connection


def test_expected_publication_revision_is_the_alembic_head() -> None:
    config = Config(str(REPO / "alembic-v2.ini"), output_buffer=StringIO())
    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == V2_ALEMBIC_HEAD_REVISION


class _RevisionSession:
    """Stands in for a Session that reads the stored revisions."""

    def __init__(self, revisions=()):
        self.revisions = revisions

    def scalars(self, _statement):
        return iter(self.revisions)


class _Inspector:
    def __init__(self, *, dialect: str = "postgresql", table_exists: bool = True):
        self.dialect = type("Dialect", (), {"name": dialect})()
        self.table_exists = table_exists

    def has_table(self, table_name: str) -> bool:
        assert table_name == "alembic_version"
        return self.table_exists


def test_revision_check_rejects_non_postgres_missing_and_wrong_revisions() -> None:
    with (
        patch.object(
            database, "v2_schema_inspector", return_value=_Inspector(dialect="sqlite")
        ),
        pytest.raises(publication.CatalogPublicationError, match="PostgreSQL"),
    ):
        publication._verify_expected_revision(_RevisionSession())

    with (
        patch.object(
            database,
            "v2_schema_inspector",
            return_value=_Inspector(table_exists=False),
        ),
        pytest.raises(publication.CatalogPublicationError, match="table is absent"),
    ):
        publication._verify_expected_revision(_RevisionSession())

    with (
        patch.object(database, "v2_schema_inspector", return_value=_Inspector()),
        pytest.raises(publication.CatalogPublicationError, match="expected"),
    ):
        publication._verify_expected_revision(
            _RevisionSession(revisions=("wrong-revision",))
        )


class _CopyBase(SQLModel, registry=registry()):
    """A declarative base of its own, so the test's table is on no real one."""


class _CopiedRow(_CopyBase, table=True):
    """A table COPY writes into."""

    __tablename__ = "stage_catalog_models"

    id: int = Field(primary_key=True)
    name: str


def test_copy_streams_rows_through_psycopg_without_an_orm_write() -> None:
    session = FakeSession()
    rows = ((index, f"row-{index}") for index in range(3))

    count = publication_staging.copy_rows(session, model=_CopiedRow, rows=rows)

    cursor = session.held_connection.connection.driver_connection.selected_cursor
    assert count == 3
    assert cursor.statement.as_string() == (
        'COPY "stage_catalog_models" ("id", "name") FROM STDIN'
    )
    assert cursor.copy_operation.rows == [
        (0, "row-0"),
        (1, "row-1"),
        (2, "row-2"),
    ]


def test_publication_uses_mapped_tables_and_sqlalchemy_statements() -> None:
    dialect = postgresql.dialect()
    # The staging tables are mapped classes on their own registry, apart from
    # the v2 models that Alembic compares, and each is TEMPORARY, dropped at
    # commit (test_database_access_boundaries checks the DDL publication sends).
    staging_registry = StagingBase._sa_registry
    assert {mapper.class_ for mapper in staging_registry.mappers} == set(STAGING_MODELS)
    assert StagingBase.metadata is not SQLModel.metadata
    assert {mapper.class_ for mapper in SQLModel._sa_registry.mappers}.isdisjoint(
        STAGING_MODELS
    )
    assert all(
        model.__table_args__ == TEMPORARY_UNTIL_COMMIT for model in STAGING_MODELS
    )

    inserts = publication_inserts.SET_BASED_INSERT_STATEMENTS
    assert all(not isinstance(statement, TextClause) for statement in inserts)
    compiled_inserts = tuple(
        str(statement.compile(dialect=dialect)) for statement in inserts
    )
    assert all("INSERT INTO" in statement for statement in compiled_inserts)
    assert all("SELECT" in statement for statement in compiled_inserts)
    assert all("VALUES" not in statement for statement in compiled_inserts)

    catalog = normalized_catalog()
    format_1_comparisons, format_2_comparisons = (
        publication_reconciliation._comparison_pairs(
            catalog.country("us"), with_format_2=with_format_2
        )
        for with_format_2 in (False, True)
    )
    region_pair = publication_reconciliation._region_comparison_pair(
        catalog.country("us")
    )
    for comparisons in (format_1_comparisons, format_2_comparisons):
        assert [table_name for table_name, _staged, _stored in comparisons] == [
            "model version",
            "variables",
            "parameter nodes",
            "parameters",
            "dynamic parameters",
            "parameter values",
            "dynamic parameter values",
            "datasets",
        ]
        pairs = (*comparisons, ("regions", *region_pair))
        assert all(
            isinstance(statement, sa.sql.Select)
            and not isinstance(statement, TextClause)
            for _table_name, *pair in pairs
            for statement in pair
        )
        assert all(
            len(staged.selected_columns) == len(stored.selected_columns)
            for _table_name, staged, stored in pairs
        )
    # Format 2 compares model versions, variables, parameters and dynamic
    # parameters on more fields. Regions are compared separately, on the same
    # fields in both formats.
    assert [
        len(format_2[1].selected_columns) - len(format_1[1].selected_columns)
        for format_1, format_2 in zip(
            format_1_comparisons, format_2_comparisons, strict=True
        )
    ] == [3, 8, 0, 2, 2, 0, 0, 0]

    class Result:
        def scalar_one(self):
            return None

    class RecordingSession:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return Result()

    session = RecordingSession()
    publication._acquire_publication_lock(session)
    assert not isinstance(session.statement, TextClause)
    compiled_lock = str(
        session.statement.compile(
            dialect=dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "pg_advisory_xact_lock" in compiled_lock
    assert str(publication.PUBLICATION_ADVISORY_LOCK_KEY) in compiled_lock


def test_completion_evidence_contains_only_reviewed_non_secret_fields() -> None:
    evidence = publication.PublicationEvidence(
        policyengine_version="4.20.3",
        dependency_versions=(("policyengine-core", "3.30.0"),),
        entity_counts={"parameters": 12},
        fallback_summaries=(("us", "state", 3),),
        elapsed_seconds=2.3456,
        omitted_region_summaries=(("us", "place", 333),),
        kept_region_summaries=(("uk", "6.7.5", 5, 1_015),),
        time_period_updates=(("us", "6.7.5", (2035, 2034, 2023, 2022), (2035, 2034)),),
        parameter_trees_written=(("policyengine-uk", "6.7.5", 2_430),),
        parameter_search_files_written=(("policyengine-uk", "6.7.5", 412_000, 61_000),),
        restored_catalog_versions=(("uk", "6.7.4", 1_172_130, 218),),
        pruned_catalog_versions=(
            publication_types.PrunedCatalogVersion(
                country_id="us",
                policyengine_version="6.6.0",
                parameter_values=1_172_130,
                dynamic_parameter_values=218,
                parameter_tree_children=101_000,
                parameter_search_files=1,
            ),
        ),
        catalog_pruning_failures=(
            publication_types.CatalogPruningFailure(
                country_id="uk",
                policyengine_version="6.6.0",
                error_type="OperationalError",
                message=(
                    "pruning the uk catalog version 6.6.0 failed and was rolled "
                    "back: the database reported QueryCanceled (SQLSTATE 57014)"
                ),
            ),
        ),
        catalog_versions_left_to_prune=3,
        catalog_tables_analyzed=("parameter_values", "parameters"),
        catalog_statistics_failure="psycopg.errors.QueryCanceled",
        spm_availability=publication_types.SPMAvailabilityRecording(
            recorded=(("uk", "2.50.0", False),),
            not_recorded=(("us", "1.450.0"),),
        ),
    ).as_dict()

    assert evidence == {
        "outcome": "ok",
        "policyengine_version": "4.20.3",
        "dependency_versions": {"policyengine-core": "3.30.0"},
        "entity_counts": {"parameters": 12},
        "fallback_summaries": [
            {"country_id": "us", "region_type": "state", "count": 3}
        ],
        "omitted_region_summaries": [
            {"country_id": "us", "region_type": "place", "count": 333}
        ],
        "kept_regions": [
            {
                "country_id": "uk",
                "policyengine_version": "6.7.5",
                "stored_regions": 5,
                "staged_regions": 1_015,
            }
        ],
        "updated_time_periods": [
            {
                "country_id": "us",
                "policyengine_version": "6.7.5",
                "previous_time_periods": [2035, 2034, 2023, 2022],
                "time_periods": [2035, 2034],
            }
        ],
        "parameter_trees_written": [
            {
                "model": "policyengine-uk",
                "version": "6.7.5",
                "rows": 2_430,
            }
        ],
        "parameter_search_files_written": [
            {
                "model": "policyengine-uk",
                "version": "6.7.5",
                "uncompressed_bytes": 412_000,
                "compressed_bytes": 61_000,
            }
        ],
        "restored_catalog_versions": [
            {
                "country_id": "uk",
                "policyengine_version": "6.7.4",
                "parameter_values": 1_172_130,
                "dynamic_parameter_values": 218,
            }
        ],
        "pruned_catalog_versions": [
            {
                "country_id": "us",
                "policyengine_version": "6.6.0",
                "deleted_rows": {
                    "parameter_values": 1_172_130,
                    "dynamic_parameter_values": 218,
                    "parameter_tree_children": 101_000,
                    "parameter_search_files": 1,
                },
            }
        ],
        "catalog_pruning_failures": [
            {
                "country_id": "uk",
                "policyengine_version": "6.6.0",
                "error_type": "OperationalError",
                "message": (
                    "pruning the uk catalog version 6.6.0 failed and was rolled "
                    "back: the database reported QueryCanceled (SQLSTATE 57014)"
                ),
            }
        ],
        "catalog_versions_left_to_prune": 3,
        "catalog_tables_analyzed": ["parameter_values", "parameters"],
        "catalog_statistics_failure": "psycopg.errors.QueryCanceled",
        "spm_availability": {
            "recorded": [{"country_id": "uk", "version": "2.50.0", "available": False}],
            "not_recorded": [{"country_id": "us", "version": "1.450.0"}],
            "versions_unreadable": None,
        },
        "elapsed_seconds": 2.346,
    }
    assert (
        not {
            "database_url",
            "credentials",
            "parameter_values",
            "artifact_location",
            "dataset_release",
        }
        & evidence.keys()
    )


def test_fallback_summary_emits_one_non_secret_warning() -> None:
    fallback_summaries = (
        ("us", "congressional_district", 436),
        ("us", "place", 333),
        ("us", "state", 51),
    )

    with patch.object(publication.LOGGER, "warning") as warning:
        publication._log_fallback_warning(fallback_summaries)

    warning.assert_called_once_with(
        "PolicyEngine.py regional dataset fallback summary: %s",
        fallback_summaries,
    )
    message_template, logged_summaries = warning.call_args.args
    rendered_message = message_template % (logged_summaries,)
    assert "regional dataset fallback summary" in rendered_message
    assert "postgresql://" not in rendered_message


def test_a_catalog_tree_needs_a_stored_row_for_every_parameter() -> None:
    """Each tree parameter references the stored parameter of the same name.

    The stored IDs differ from the catalog's, so the tree must take them from
    the stored rows, not from the catalog records.
    """
    country = normalized_catalog().country("us")
    stored_ids = {parameter.name: uuid4() for parameter in country.parameters}

    rows = catalog_parameter_tree(country, stored_ids)
    leaves = [row for row in rows if row.child_type == "parameter"]

    assert [(row.path, row.parameter_id) for row in leaves] == [
        (parameter.name, stored_ids[parameter.name]) for parameter in country.parameters
    ]
    assert {row.parameter_id for row in leaves}.isdisjoint(
        parameter.id for parameter in country.parameters
    )
    with pytest.raises(
        CatalogPublicationError,
        match=re.escape(
            f"the stored us catalog version {country.model_version.version} "
            "lacks the parameter gov.example.rate"
        ),
    ):
        catalog_parameter_tree(country, {})


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_a_catalog_tree_leaves_out_model_assumptions_and_their_folders(
    country_id: str,
) -> None:
    """The policy tree holds only policy parameters, from catalog format 2 on.

    Model assumptions are stored in ``dynamic_parameters``, so the tree needs
    stored rows only for the other parameters, and neither the assumptions nor
    their folders (``gov.simulation``, US ``simulation``, UK ``gov.dynamic``)
    are rows of it, although the nodes table holds those folders.
    """
    country = catalog_with_dynamic_parameters().country(country_id)
    policy_parameter_ids = {
        parameter.name: uuid4()
        for parameter in country.parameters
        if not is_dynamic_parameter(country_id, parameter.name)
    }
    assert any(
        is_dynamic_parameter_path(country_id, node.name)
        for node in country.parameter_nodes
    )

    rows = catalog_parameter_tree(country, policy_parameter_ids)

    assert {row.path for row in rows if row.child_type == "parameter"} == set(
        policy_parameter_ids
    )
    assert not [
        row.path for row in rows if is_dynamic_parameter_path(country_id, row.path)
    ]
    assert {row.path for row in rows if row.parent_path == ""} == {"gov"}
    (gov,) = (row for row in rows if row.path == "gov")
    assert gov.child_count == 1


def _kept_region_records(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    differences: tuple[int, int],
) -> list[logging.LogRecord]:
    monkeypatch.setattr(
        publication,
        "count_region_differences",
        lambda _session, _country: differences,
    )
    monkeypatch.setattr(publication, "count_stored_regions", lambda *_args: 4)
    # An earlier test's Alembic logging setup may have disabled existing loggers.
    monkeypatch.setattr(publication.LOGGER, "disabled", False)
    us = normalized_catalog().country("us")
    with caplog.at_level(logging.WARNING, logger=publication.LOGGER.name):
        summary = publication._kept_region_summary(object(), us)
    assert summary == (None if differences == (0, 0) else ("us", "5.0.4", 4, 3))
    return [
        record for record in caplog.records if record.name == publication.LOGGER.name
    ]


def test_kept_region_warning_prints_country_version_and_counts_without_logging_setup(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    [record] = _kept_region_records(monkeypatch, caplog, (1, 2))

    # The seed command configures no logging, so Python's last-resort handler
    # prints the record; this is the text the job output shows.
    assert logging.lastResort is not None
    assert logging.lastResort.format(record) == (
        "kept the published regions of the stored us catalog version 5.0.4: "
        "1 staged region rows are not stored and 2 stored region rows are not "
        "staged"
    )
    assert record.levelno == logging.WARNING
    assert record.policyengine_attributes == {
        "country_id": "us",
        "policyengine_version": "5.0.4",
        "staged_region_rows_not_stored": 1,
        "stored_region_rows_not_staged": 2,
    }


def test_matching_kept_regions_log_nothing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert _kept_region_records(monkeypatch, caplog, (0, 0)) == []


def test_stored_versions_are_compared_without_their_time_periods() -> None:
    """Publication replaces them instead (``update_stored_time_periods``)."""
    dialect = postgresql.dialect()
    country = normalized_catalog().country("us")
    for with_format_2 in (False, True):
        [(table_name, staged, stored), *_others] = (
            publication_reconciliation._comparison_pairs(
                country, with_format_2=with_format_2
            )
        )
        assert table_name == "model version"
        for statement in (staged, stored):
            assert "current_law_id" in str(statement.compile(dialect=dialect))
            assert "metadata_time_periods" not in str(
                statement.compile(dialect=dialect)
            )


def _time_period_update_records(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    update: tuple[list[int], list[int]] | None,
) -> tuple[object, list[logging.LogRecord]]:
    monkeypatch.setattr(
        publication,
        "update_stored_time_periods",
        lambda _session, _country: update,
    )
    # An earlier test's Alembic logging setup may have disabled existing loggers.
    monkeypatch.setattr(publication.LOGGER, "disabled", False)
    us = normalized_catalog().country("us")
    with caplog.at_level(logging.WARNING, logger=publication.LOGGER.name):
        summary = publication._time_period_update(object(), us)
    return summary, [
        record for record in caplog.records if record.name == publication.LOGGER.name
    ]


def test_time_period_update_warning_prints_country_version_and_years(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    summary, [record] = _time_period_update_records(
        monkeypatch, caplog, ([2025, 2024, 2023, 2022], [2025, 2024])
    )

    assert summary == ("us", "5.0.4", (2025, 2024, 2023, 2022), (2025, 2024))
    # The seed command configures no logging, so Python's last-resort handler
    # prints the record; this is the text the job output shows.
    assert logging.lastResort is not None
    assert logging.lastResort.format(record) == (
        "replaced the time periods of the stored us catalog version 5.0.4: "
        "[2025, 2024, 2023, 2022] became [2025, 2024]"
    )
    assert record.levelno == logging.WARNING
    assert record.policyengine_attributes == {
        "country_id": "us",
        "policyengine_version": "5.0.4",
        "stored_time_periods": [2025, 2024, 2023, 2022],
        "staged_time_periods": [2025, 2024],
    }


def test_matching_time_periods_log_nothing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert _time_period_update_records(monkeypatch, caplog, None) == (None, [])
