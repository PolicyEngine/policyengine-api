from io import StringIO

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest

from policyengine_api.constants import REPO
from policyengine_api.data.v1_models import V1Base


def _mysql_offline_config() -> tuple[Config, StringIO]:
    output = StringIO()
    config = Config(str(REPO / "alembic.ini"), output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url",
        "mysql+pymysql://offline:offline@localhost/offline",
    )
    return config, output


def test_default_configuration_requires_an_explicit_database_url(monkeypatch):
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    config = Config(str(REPO / "alembic.ini"), output_buffer=StringIO())

    with pytest.raises(RuntimeError, match="ALEMBIC_DATABASE_URL"):
        command.upgrade(config, "head", sql=True)


def test_sqlite_is_rejected_as_a_migration_target(monkeypatch):
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    config = Config(str(REPO / "alembic.ini"), output_buffer=StringIO())

    with pytest.raises(RuntimeError, match="MySQL"):
        command.upgrade(config, "head", sql=True)


def test_baseline_renders_the_v1_schema_for_mysql_without_connecting():
    config, output = _mysql_offline_config()

    command.upgrade(config, "head", sql=True)

    rendered_sql = output.getvalue()
    for table_name in V1Base.metadata.tables:
        assert f"CREATE TABLE {table_name}" in rendered_sql
    assert "CREATE TABLE alembic_version" in rendered_sql


def test_baseline_is_the_single_root_revision():
    config, _ = _mysql_offline_config()
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_revision(scripts.get_current_head())

    assert head is not None
    assert head.down_revision is None


def test_baseline_renders_a_complete_mysql_downgrade_without_connecting():
    config, output = _mysql_offline_config()

    command.downgrade(config, "head:base", sql=True)

    rendered_sql = output.getvalue()
    for table_name in V1Base.metadata.tables:
        assert f"DROP TABLE {table_name}" in rendered_sql
