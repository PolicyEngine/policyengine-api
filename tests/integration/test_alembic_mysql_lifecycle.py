"""Exercise the complete Alembic lifecycle against an ephemeral MySQL schema."""

import os

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.engine import make_url

from policyengine_api.constants import REPO
from policyengine_api.data.v1_models import V1Base
from scripts.v1_database_migration import (
    ADOPTION_CONFIRMATION,
    DatabaseState,
    adopt_database,
    database_state,
)


BASELINE_REVISION = "eafc2a547a4e"


def _deployed_question_table() -> Table:
    """Describe the orphaned production table without adding it to ORM metadata."""

    metadata = MetaData()
    return Table(
        "question",
        metadata,
        Column("question_id", Integer, primary_key=True, autoincrement=True),
        Column("question", Text().with_variant(LONGTEXT(), "mysql"), nullable=False),
        Column("answer", Text().with_variant(LONGTEXT(), "mysql")),
        Column("policy_id", Integer),
        Column("country_id", String(3), nullable=False),
        Column("subtask", String(32), nullable=False),
        Column("status", String(32), nullable=False),
    )


def _ephemeral_mysql_url() -> str:
    database_url = os.environ.get("ALEMBIC_DATABASE_URL", "")
    if not database_url:
        pytest.skip("ALEMBIC_DATABASE_URL is not set")

    url = make_url(database_url)
    if url.get_backend_name() != "mysql":
        pytest.fail("ALEMBIC_DATABASE_URL must use MySQL for this test")
    if url.host not in {"127.0.0.1", "localhost"}:
        pytest.fail("Alembic lifecycle tests may only target local MySQL")
    if url.database != "policyengine_alembic_test":
        pytest.fail(
            "Alembic lifecycle tests require the policyengine_alembic_test schema"
        )
    return database_url


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO / "alembic-v1.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_fresh_upgrade_check_downgrade_and_reupgrade():
    database_url = _ephemeral_mysql_url()
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    question = _deployed_question_table()

    try:
        command.downgrade(config, "base")
        question.drop(engine, checkfirst=True)
        command.upgrade(config, "head")
        command.check(config)

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() is not None
            assert compare_metadata(context, V1Base.metadata) == []

        inspector = inspect(engine)
        assert "tracers" not in inspector.get_table_names()
        reform_impact_columns = {
            column["name"]: column for column in inspector.get_columns("reform_impact")
        }
        assert reform_impact_columns["dataset"]["default"] is None
        assert reform_impact_columns["execution_id"]["nullable"] is False

        command.downgrade(config, BASELINE_REVISION)
        assert "question" in inspect(engine).get_table_names()

        command.upgrade(config, "head")
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() is not None
            assert compare_metadata(context, V1Base.metadata) == []
    finally:
        engine.dispose()


def test_upgrade_removes_orphaned_question_table_and_downgrade_restores_schema(
    monkeypatch,
):
    database_url = _ephemeral_mysql_url()
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    question = _deployed_question_table()

    try:
        command.downgrade(config, "base")
        question.drop(engine, checkfirst=True)
        command.upgrade(config, BASELINE_REVISION)
        question.create(engine)
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            operations.drop_table("tracers")
            operations.alter_column(
                "reform_impact",
                "execution_id",
                existing_type=String(255),
                nullable=True,
            )
            operations.alter_column(
                "reform_impact",
                "dataset",
                existing_type=String(255),
                existing_nullable=False,
                server_default=text("'default'"),
            )
            connection.execute(
                question.insert(),
                {
                    "question": "Historical prototype",
                    "country_id": "uk",
                    "subtask": "complete",
                    "status": "ok",
                },
            )
            operations.drop_table("alembic_version")

        with engine.begin() as connection:
            monkeypatch.delenv("ALEMBIC_DATABASE_URL")
            adopt_database(
                connection,
                confirmation=ADOPTION_CONFIRMATION,
                backup_id="test-backup",
                expected_question_rows=1,
            )

        with engine.connect() as connection:
            assert database_state(connection) is DatabaseState.HEAD

        inspector = inspect(engine)
        assert "question" not in inspector.get_table_names()
        assert "tracers" not in inspector.get_table_names()
        reform_impact_columns = {
            column["name"]: column for column in inspector.get_columns("reform_impact")
        }
        assert reform_impact_columns["dataset"]["default"] is None
        assert reform_impact_columns["execution_id"]["nullable"] is False

        command.downgrade(config, BASELINE_REVISION)

        assert "question" in inspect(engine).get_table_names()
        assert {
            column["name"] for column in inspect(engine).get_columns("question")
        } == {
            "question_id",
            "question",
            "answer",
            "policy_id",
            "country_id",
            "subtask",
            "status",
        }
    finally:
        command.upgrade(config, "head")
        engine.dispose()
