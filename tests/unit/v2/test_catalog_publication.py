"""Focused structural tests for PostgreSQL catalog publication."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest

from policyengine_api.data.v2.catalog import publication


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
    def __init__(self) -> None:
        self.connection = type(
            "ConnectionProxy",
            (),
            {"driver_connection": FakeDriverConnection()},
        )()


def test_expected_publication_revision_is_the_alembic_head() -> None:
    config = Config(str(REPO / "alembic-v2.ini"), output_buffer=StringIO())
    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == publication.EXPECTED_ALEMBIC_REVISION


class _ScalarResult:
    def __init__(self, value=None, values=()):
        self.value = value
        self.values = values

    def scalar_one(self):
        return self.value

    def scalars(self):
        return iter(self.values)


class _RevisionConnection:
    def __init__(self, *, dialect: str, version_table=None, revisions=()):
        self.dialect = type("Dialect", (), {"name": dialect})()
        self.results = iter(
            (
                _ScalarResult(value=version_table),
                _ScalarResult(values=revisions),
            )
        )

    def execute(self, _statement):
        return next(self.results)


def test_revision_check_rejects_non_postgres_missing_and_wrong_revisions() -> None:
    with pytest.raises(publication.CatalogPublicationError, match="PostgreSQL"):
        publication._verify_expected_revision(_RevisionConnection(dialect="sqlite"))

    with pytest.raises(publication.CatalogPublicationError, match="table is absent"):
        publication._verify_expected_revision(
            _RevisionConnection(dialect="postgresql", version_table=None)
        )

    with pytest.raises(publication.CatalogPublicationError, match="expected"):
        publication._verify_expected_revision(
            _RevisionConnection(
                dialect="postgresql",
                version_table="alembic_version",
                revisions=("wrong-revision",),
            )
        )


def test_copy_streams_rows_through_psycopg_without_an_orm_write() -> None:
    connection = FakeConnection()
    rows = ((index, f"row-{index}") for index in range(3))

    count = publication._copy_rows(
        connection,
        table_name="stage_catalog_models",
        columns=("id", "name"),
        rows=rows,
    )

    cursor = connection.connection.driver_connection.selected_cursor
    assert count == 3
    assert cursor.statement == ("COPY stage_catalog_models (id, name) FROM STDIN")
    assert cursor.copy_operation.rows == [
        (0, "row-0"),
        (1, "row-1"),
        (2, "row-2"),
    ]


def test_publication_sql_uses_private_staging_and_set_based_inserts() -> None:
    assert all(
        "CREATE TEMP TABLE" in statement and "ON COMMIT DROP" in statement
        for statement in publication.TEMP_TABLE_STATEMENTS
    )
    assert all(
        "INSERT INTO" in statement for statement in publication.SET_BASED_INSERT_SQL
    )
    assert all("SELECT" in statement for statement in publication.SET_BASED_INSERT_SQL)
    assert all(
        "VALUES" not in statement for statement in publication.SET_BASED_INSERT_SQL
    )

    class Result:
        def scalar_one(self):
            return None

    class Connection:
        statement = ""
        parameters = {}

        def execute(self, statement, parameters):
            self.statement = str(statement)
            self.parameters = parameters
            return Result()

    connection = Connection()
    publication._acquire_publication_lock(connection)
    assert "pg_advisory_xact_lock" in connection.statement
    assert connection.parameters == {
        "lock_key": publication.PUBLICATION_ADVISORY_LOCK_KEY
    }


def test_completion_evidence_contains_only_reviewed_non_secret_fields() -> None:
    evidence = publication.PublicationEvidence(
        policyengine_version="4.20.3",
        dependency_versions=(("policyengine-core", "3.30.0"),),
        entity_counts={"parameters": 12},
        fallback_summaries=(("us", "state", 3),),
        elapsed_seconds=2.3456,
    ).as_dict()

    assert evidence == {
        "outcome": "ok",
        "policyengine_version": "4.20.3",
        "dependency_versions": {"policyengine-core": "3.30.0"},
        "entity_counts": {"parameters": 12},
        "fallback_summaries": [
            {"country_id": "us", "region_type": "state", "count": 3}
        ],
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
