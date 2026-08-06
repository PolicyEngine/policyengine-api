"""Qualification of an existing pre-Alembic v1 schema."""

import os

from alembic import command
import pytest
from sqlalchemy import inspect, text

from policyengine_api.scripts.qualify_stage7_toy import compare_stage7_schema
from tests.integration.stage7_mysql import (
    alembic_config,
    create_pre_alembic_schema,
    reset_toy_database,
    schema_signature,
)


def test_fresh_upgrade_has_the_same_schema_signature_as_pre_alembic_v1(stage7_mysql):
    database_url, engine = stage7_mysql
    create_pre_alembic_schema(engine)
    pre_alembic = schema_signature(engine)

    reset_toy_database(engine, database_url)
    command.upgrade(alembic_config(database_url), "head")
    fresh_upgrade = schema_signature(engine)
    fresh_upgrade.pop("alembic_version")

    assert fresh_upgrade == pre_alembic


def test_existing_schema_compares_read_only_and_stamps_without_data_loss(
    stage7_mysql,
):
    database_url, engine = stage7_mysql
    create_pre_alembic_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO policy "
                "(id, country_id, label, api_version, policy_json, policy_hash) "
                "VALUES (901, 'us', 'sentinel', 'legacy', '{}', 'sentinel')"
            )
        )

    before_comparison = schema_signature(engine)
    assert "alembic_version" not in before_comparison
    assert compare_stage7_schema(database_url) == []
    assert schema_signature(engine) == before_comparison

    config = alembic_config(database_url)
    command.stamp(config, "head")
    command.check(config)

    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT label FROM policy WHERE id = 901"))
            == "sentinel"
        )
    assert inspect(engine).get_table_names().count("alembic_version") == 1


@pytest.mark.skipif(
    "STAGE7_EXISTING_DATABASE_URL" not in os.environ,
    reason="A read-only existing Cloud SQL URL was not supplied",
)
def test_live_existing_schema_matches_metadata_without_mutation():
    database_url = os.environ["STAGE7_EXISTING_DATABASE_URL"]
    assert compare_stage7_schema(database_url) == []
