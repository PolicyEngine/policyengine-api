"""MySQL qualification for the disposable Stage 7 database."""

from alembic import command
from sqlalchemy import inspect

from policyengine_api.data.v1_models import V1Base
from policyengine_api.scripts.qualify_stage7_toy import (
    compare_stage7_schema,
    qualify_stage7_toy,
)
from tests.integration.stage7_mysql import alembic_config


def test_mysql_toy_database_upgrades_and_exercises_every_dao_domain(stage7_mysql):
    database_url, _ = stage7_mysql
    result = qualify_stage7_toy(database_url)

    assert result == {
        "alembic_head": True,
        "policy": True,
        "household": True,
        "computed_household": True,
        "user": True,
        "user_policy": True,
        "economy": True,
        "simulation": True,
        "report": True,
        "report_alias": True,
        "analysis": True,
        "tracer": True,
        "reform_impact": True,
    }
    assert compare_stage7_schema(database_url) == []


def test_mysql_toy_database_downgrades_and_reupgrades_cleanly(stage7_mysql):
    database_url, engine = stage7_mysql
    config = alembic_config(database_url)
    qualify_stage7_toy(database_url)

    command.downgrade(config, "base")
    remaining_tables = set(inspect(engine).get_table_names())
    assert not set(V1Base.metadata.tables) & remaining_tables

    command.upgrade(config, "head")
    command.check(config)
    assert compare_stage7_schema(database_url) == []
