from __future__ import annotations

from contextlib import nullcontext

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, text

import scripts.v1_database_migration as migration
from scripts.v1_alembic_changes import is_v1_alembic_path
from scripts.v1_database_migration import (
    ADOPTION_CONFIRMATION,
    BASELINE_REVISION,
    DatabaseState,
    build_database_url,
    classify_database_state,
    describe_metadata_difference,
    require_adoption_confirmation,
)


@pytest.mark.parametrize(
    "path",
    [
        "alembic-v1.ini",
        "migrations/v1/env.py",
        "migrations/v1/versions/123_add_column.py",
        "policyengine_api/data/v1_models.py",
        "scripts/v1_database_migration.py",
        "tests/integration/test_alembic_mysql_lifecycle.py",
        "tests/integration/test_v1_schema_metadata_compatibility.py",
        ".github/workflows/alembic-v1-check.yml",
        "docs/engineering/skills/alembic-migrations.md",
        "pyproject.toml",
        "uv.lock",
    ],
)
def test_v1_alembic_change_paths_trigger_qualification(path):
    assert is_v1_alembic_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "policyengine_api/routes/household_routes.py",
        "tests/unit/routes/test_household_routes.py",
        "docs/migration/cloud-run-operations.md",
        ".github/workflows/push.yml",
    ],
)
def test_unrelated_paths_do_not_trigger_v1_alembic_qualification(path):
    assert not is_v1_alembic_path(path)


def test_database_url_percent_encodes_credentials_without_losing_driver():
    url = build_database_url(
        username="schema reader",
        password="p@ss:/word",
        host="127.0.0.1",
        port=3307,
        database="policyengine",
    )

    assert url == (
        "mysql+pymysql://schema+reader:p%40ss%3A%2Fword@127.0.0.1:3307/policyengine"
    )


def test_database_state_is_unversioned_without_a_version_table():
    assert (
        classify_database_state(version_table_exists=False, current_heads=set())
        is DatabaseState.UNVERSIONED
    )


def test_database_state_is_invalid_when_version_table_has_no_revision():
    assert (
        classify_database_state(version_table_exists=True, current_heads=set())
        is DatabaseState.INVALID
    )


def test_database_state_is_head_only_when_all_script_heads_are_applied():
    assert (
        classify_database_state(
            version_table_exists=True,
            current_heads={"head-a"},
            script_heads={"head-a"},
        )
        is DatabaseState.HEAD
    )
    assert (
        classify_database_state(
            version_table_exists=True,
            current_heads={BASELINE_REVISION},
            script_heads={"head-a"},
        )
        is DatabaseState.PENDING
    )


def test_adoption_requires_the_exact_explicit_confirmation():
    require_adoption_confirmation(ADOPTION_CONFIRMATION)

    with pytest.raises(ValueError, match="confirmation"):
        require_adoption_confirmation("yes")


def test_metadata_difference_descriptions_are_stable_and_do_not_include_data():
    metadata = MetaData()
    question = Table(
        "question",
        metadata,
        Column("question_id", Integer, primary_key=True),
        Column("question", String(255)),
    )

    assert describe_metadata_difference(("remove_table", question)) == (
        "extra_table:question"
    )
    assert (
        describe_metadata_difference(
            [
                (
                    "modify_nullable",
                    None,
                    "reform_impact",
                    "execution_id",
                    {},
                    True,
                    False,
                )
            ]
        )
        == "nullable:reform_impact.execution_id:true->false"
    )
    assert (
        describe_metadata_difference(
            [
                (
                    "modify_default",
                    None,
                    "reform_impact",
                    "dataset",
                    {},
                    text("'default'"),
                    None,
                )
            ]
        )
        == "default:reform_impact.dataset:present->none"
    )


def test_metadata_difference_rejects_unknown_shapes_without_repr_leakage():
    secret = "do-not-print-this-value"
    difference = ("unknown", secret)

    with pytest.raises(ValueError, match="Unsupported metadata difference") as error:
        describe_metadata_difference(difference)

    assert secret not in str(error.value)


def test_adoption_cli_commits_the_externally_supplied_connection(monkeypatch):
    connection = object()

    class FakeEngine:
        def begin(self):
            return nullcontext(connection)

        def connect(self):
            raise AssertionError("adoption must use a committing transaction")

        def dispose(self):
            pass

    calls = []
    monkeypatch.setattr(
        migration, "create_engine", lambda *args, **kwargs: FakeEngine()
    )
    monkeypatch.setattr(
        migration,
        "adopt_database",
        lambda supplied_connection, **kwargs: calls.append(
            (supplied_connection, kwargs)
        ),
    )
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "mysql+pymysql://unused")

    assert (
        migration.main(
            [
                "--mode",
                "adopt",
                "--confirmation",
                ADOPTION_CONFIRMATION,
                "--backup-id",
                "verified-backup",
            ]
        )
        == 0
    )
    assert calls == [
        (
            connection,
            {
                "confirmation": ADOPTION_CONFIRMATION,
                "backup_id": "verified-backup",
                "expected_question_rows": 9,
            },
        )
    ]
