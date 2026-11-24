from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.engine import URL

import scripts.v1_database_migration as migration
from policyengine_api.constants import REPO
from scripts.v1_database_migration import (
    DatabaseState,
    build_database_url,
    classify_database_state,
    describe_metadata_difference,
    upgrade_database,
)

if TYPE_CHECKING:
    from pathlib import Path

# Fake credentials; the first holds characters that URLs must escape.
FAKE_PASSWORD_WITH_URL_CHARACTERS = "p@ss:/word"
FAKE_PASSWORD = "p@ssword"
# The database URLs .github/scripts/migrate_v1_cloud_sql.sh unsets before it
# runs the script, so only the credentials it fetched reach the database.
UNSET_DATABASE_URL_NAMES = ("ALEMBIC_DATABASE_URL", "STAGE7_EXISTING_DATABASE_URL")
# Imports the script, then prints the named variables as JSON on its last line.
IMPORT_SCRIPT_AND_REPORT_VARIABLES = """
import json
import os
import sys

import scripts.v1_database_migration

print(json.dumps({name: os.environ.get(name) for name in sys.argv[1:]}))
"""
SUBPROCESS_TIMEOUT_SECONDS = 120


def test_importing_the_script_loads_no_dotenv_file(tmp_path: Path) -> None:
    """A .env file can't give the script back a database URL the deploy unset.

    Run through ``python -c``, python-dotenv searches for ``.env`` from the
    working directory, so a default ``load_dotenv()`` anywhere in the script's
    imports would find the file written here.
    """
    (tmp_path / ".env").write_text(
        "".join(
            f"{name}=mysql+pymysql://from-dotenv@127.0.0.1:3307/policyengine\n"
            for name in UNSET_DATABASE_URL_NAMES
        ),
        encoding="utf-8",
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in UNSET_DATABASE_URL_NAMES
    }
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO), *filter(None, [os.environ.get("PYTHONPATH")])]
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            IMPORT_SCRIPT_AND_REPORT_VARIABLES,
            *UNSET_DATABASE_URL_NAMES,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )

    assert completed.returncode == 0, completed.stderr
    reported_variables = json.loads(completed.stdout.splitlines()[-1])
    assert reported_variables == dict.fromkeys(UNSET_DATABASE_URL_NAMES)


def test_database_url_uses_sqlalchemy_url_without_stringifying_credentials():
    url = build_database_url(
        username="schema reader",
        password=FAKE_PASSWORD_WITH_URL_CHARACTERS,
        host="127.0.0.1",
        port=3307,
        database="policyengine",
    )

    assert isinstance(url, URL)
    assert url.username == "schema reader"
    assert url.password == FAKE_PASSWORD_WITH_URL_CHARACTERS
    assert url.host == "127.0.0.1"
    assert url.port == 3307
    assert url.database == "policyengine"


@pytest.mark.parametrize(
    ("mode", "password_name", "expected_user"),
    [
        ("state", "POLICYENGINE_DB_READONLY_PASSWORD", "policyengine_schema_reader"),
        (
            "verify-head",
            "POLICYENGINE_DB_READONLY_PASSWORD",
            "policyengine_schema_reader",
        ),
        (
            "upgrade",
            "POLICYENGINE_DB_MIGRATION_PASSWORD",
            "policyengine_schema_migrator",
        ),
    ],
)
def test_database_target_builds_in_memory_url_for_each_database_role(
    monkeypatch,
    mode,
    password_name,
    expected_user,
):
    monkeypatch.delenv("STAGE7_EXISTING_DATABASE_URL", raising=False)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setenv(password_name, FAKE_PASSWORD)

    target = migration._database_target(mode)

    assert isinstance(target, URL)
    assert target.username == expected_user
    assert target.password == FAKE_PASSWORD
    assert target.host == "127.0.0.1"
    assert target.port == 3307
    assert target.database == "policyengine"


def test_database_target_preserves_explicit_url_override(monkeypatch):
    explicit_url = "mysql+pymysql://root:test@127.0.0.1/test"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", explicit_url)
    monkeypatch.delenv("POLICYENGINE_DB_MIGRATION_PASSWORD", raising=False)

    assert migration._database_target("upgrade") == explicit_url


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
            current_heads={"previous-revision"},
            script_heads={"head-a"},
        )
        is DatabaseState.PENDING
    )


def test_metadata_difference_descriptions_are_stable_and_do_not_include_data():
    # Alembic names an extra table by the table it reflected, of which only the
    # name is described.
    question = SimpleNamespace(name="question")

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
                    "'default'",
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


def test_upgrade_cli_commits_the_session_it_supplies(monkeypatch):
    session = object()
    opened_urls = []

    class FakeSessions:
        def begin(self):
            return nullcontext(session)

        def __call__(self):
            msg = "upgrade must use a committing transaction"
            raise AssertionError(msg)

    @contextmanager
    def unpooled_v1_sessions(url):
        opened_urls.append(url)
        yield FakeSessions()

    calls = []
    monkeypatch.setattr(migration, "unpooled_v1_sessions", unpooled_v1_sessions)
    monkeypatch.setattr(
        migration,
        "upgrade_database",
        lambda supplied_session, **kwargs: calls.append((supplied_session, kwargs)),
    )
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "mysql+pymysql://unused")

    assert (
        migration.main(
            [
                "--mode",
                "upgrade",
                "--backup-id",
                "verified-backup",
            ]
        )
        == 0
    )
    assert opened_urls == ["mysql+pymysql://unused"]
    assert calls == [
        (
            session,
            {
                "backup_id": "verified-backup",
            },
        )
    ]


@pytest.mark.parametrize("state", [DatabaseState.UNVERSIONED, DatabaseState.INVALID])
def test_upgrade_refuses_databases_without_valid_revision_history(monkeypatch, state):
    class FakeSession:
        def scalar(self, *_args, **_kwargs):
            return 1

        def execute(self, *args, **kwargs):
            pass

    monkeypatch.setattr(migration, "database_state", lambda _session: state)

    with pytest.raises(RuntimeError, match="no valid Alembic revision"):
        upgrade_database(FakeSession(), backup_id="verified-backup")


@pytest.mark.parametrize(
    ("difference", "message"),
    [
        (("remove_table",), "Unsupported metadata difference operation: remove_table"),
        (
            ("modify_nullable", None, "t", "c", {}, True),
            "Unsupported metadata difference operation: modify_nullable",
        ),
        (
            ("modify_default", None, "t", "c", {}, None),
            "Unsupported metadata difference operation: modify_default",
        ),
        ((), "Unsupported metadata difference shape"),
        ([], "Unsupported metadata difference shape"),
        (
            [("remove_table",), ("remove_table",)],
            "Unsupported metadata difference shape",
        ),
        ("remove_table", "Unsupported metadata difference shape"),
    ],
)
def test_metadata_difference_rejects_short_or_unknown_shapes(
    difference: object, message: str
) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        describe_metadata_difference(difference)


def test_metadata_difference_accepts_longer_tuples_and_unwraps_one_item_lists() -> None:
    assert (
        describe_metadata_difference(
            [("modify_default", None, "t", "c", {}, None, "now()", "extra")]
        )
        == "default:t.c:none->present"
    )
    assert (
        describe_metadata_difference(
            ("modify_nullable", "schema", "t", "c", {}, False, True)
        )
        == "nullable:t.c:false->true"
    )
