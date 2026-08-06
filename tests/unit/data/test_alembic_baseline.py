from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from policyengine_api.constants import REPO
from policyengine_api.data.v1_models import V1Base


def _config(url: str) -> Config:
    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_baseline_upgrades_fresh_database_to_v1_head(tmp_path: Path):
    database_path = tmp_path / "fresh.db"
    command.upgrade(_config(f"sqlite+pysqlite:///{database_path}"), "head")

    tables = set(
        inspect(create_engine(f"sqlite+pysqlite:///{database_path}")).get_table_names()
    )
    assert set(V1Base.metadata.tables) <= tables
    assert "alembic_version" in tables


def test_baseline_downgrades_and_reupgrades(tmp_path: Path):
    database_path = tmp_path / "roundtrip.db"
    config = _config(f"sqlite+pysqlite:///{database_path}")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    assert set(V1Base.metadata.tables) <= set(
        inspect(create_engine(f"sqlite+pysqlite:///{database_path}")).get_table_names()
    )
