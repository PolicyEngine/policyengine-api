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
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql.elements import TextClause

from policyengine_api.data.v2.catalog import (
    publication,
    publication_reconciliation,
    publication_staging,
)
from policyengine_api.data.v2.catalog.publication_parameter_tree import (
    catalog_parameter_tree,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.migration_target import V2_ALEMBIC_HEAD_REVISION
from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)
from tests.fixtures.v2_catalog import normalized_catalog

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

    assert script.get_current_head() == V2_ALEMBIC_HEAD_REVISION


class _ScalarResult:
    def __init__(self, value=None, values=()):
        self.value = value
        self.values = values

    def scalar_one(self):
        return self.value

    def scalars(self):
        return iter(self.values)


class _RevisionConnection:
    def __init__(self, *, dialect: str, revisions=()):
        self.dialect = type("Dialect", (), {"name": dialect})()
        self.result = _ScalarResult(values=revisions)

    def execute(self, _statement):
        return self.result


class _Inspector:
    def __init__(self, *, table_exists: bool):
        self.table_exists = table_exists

    def has_table(self, table_name: str) -> bool:
        assert table_name == "alembic_version"
        return self.table_exists


def test_revision_check_rejects_non_postgres_missing_and_wrong_revisions() -> None:
    with pytest.raises(publication.CatalogPublicationError, match="PostgreSQL"):
        publication._verify_expected_revision(_RevisionConnection(dialect="sqlite"))

    with (
        patch.object(
            publication.sa, "inspect", return_value=_Inspector(table_exists=False)
        ),
        pytest.raises(publication.CatalogPublicationError, match="table is absent"),
    ):
        publication._verify_expected_revision(_RevisionConnection(dialect="postgresql"))

    with (
        patch.object(
            publication.sa, "inspect", return_value=_Inspector(table_exists=True)
        ),
        pytest.raises(publication.CatalogPublicationError, match="expected"),
    ):
        publication._verify_expected_revision(
            _RevisionConnection(
                dialect="postgresql",
                revisions=("wrong-revision",),
            )
        )


def test_copy_streams_rows_through_psycopg_without_an_orm_write() -> None:
    connection = FakeConnection()
    rows = ((index, f"row-{index}") for index in range(3))
    copy_table = sa.Table(
        "stage_catalog_models",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("name", sa.Text),
    )

    count = publication_staging.copy_rows(
        connection,
        table=copy_table,
        rows=rows,
    )

    cursor = connection.connection.driver_connection.selected_cursor
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
    assert (
        Dataset.__table__,
        TaxBenefitModel.__table__,
        TaxBenefitModelVersion.__table__,
        Parameter.__table__,
        ParameterNode.__table__,
        ParameterValue.__table__,
        Region.__table__,
        Variable.__table__,
    ) == (
        publication_reconciliation.DATASETS,
        publication_reconciliation.MODELS,
        publication_reconciliation.MODEL_VERSIONS,
        publication_reconciliation.PARAMETERS,
        publication_reconciliation.PARAMETER_NODES,
        publication_reconciliation.PARAMETER_VALUES,
        publication_reconciliation.REGIONS,
        publication_reconciliation.VARIABLES,
    )
    staging_ddl = tuple(
        str(CreateTable(table).compile(dialect=dialect))
        for table in publication_staging.STAGING_TABLES
    )
    assert all(
        "CREATE TEMPORARY TABLE" in statement and "ON COMMIT DROP" in statement
        for statement in staging_ddl
    )

    inserts = publication_reconciliation.SET_BASED_INSERT_STATEMENTS
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
    for comparisons in (format_1_comparisons, format_2_comparisons):
        assert [table_name for table_name, _staged, _stored in comparisons] == [
            "model version",
            "variables",
            "parameter nodes",
            "parameters",
            "parameter values",
            "datasets",
        ]
        statements = [
            statement for _table_name, *pair in comparisons for statement in pair
        ] + list(
            publication_reconciliation._region_comparison_pair(catalog.country("us"))
        )
        assert all(
            isinstance(statement, sa.sql.Select)
            and not isinstance(statement, TextClause)
            for statement in statements
        )
        assert all(
            len(staged.selected_columns) == len(stored.selected_columns)
            for _table_name, staged, stored in comparisons
        )
    # Format 2 compares model versions, variables and parameters on more fields.
    assert [
        len(format_2[1].selected_columns) - len(format_1[1].selected_columns)
        for format_1, format_2 in zip(
            format_1_comparisons, format_2_comparisons, strict=True
        )
    ] == [3, 8, 0, 2, 0, 0]

    class Result:
        def scalar_one(self):
            return None

    class Connection:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return Result()

    connection = Connection()
    publication._acquire_publication_lock(connection)
    assert not isinstance(connection.statement, TextClause)
    compiled_lock = str(
        connection.statement.compile(
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
        parameter_trees_written=(("policyengine-uk", "6.7.5", 2_430),),
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
        "parameter_trees_written": [
            {
                "model": "policyengine-uk",
                "version": "6.7.5",
                "rows": 2_430,
            }
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


def _kept_region_records(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    differences: tuple[int, int],
) -> list[logging.LogRecord]:
    monkeypatch.setattr(
        publication,
        "count_region_differences",
        lambda _connection, _country: differences,
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
