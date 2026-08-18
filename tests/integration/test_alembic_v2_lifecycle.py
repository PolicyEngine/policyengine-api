"""Exercise the isolated v2 Alembic lifecycle against disposable Postgres."""

import os

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, inspect, text

from policyengine_api.constants import REPO
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    V2MigrationTargetError,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.data.v2.table_inventory import EXPECTED_V2_TABLES


BASELINE_REVISION = "47592781336f"
PREVIOUS_HEAD_REVISION = "b4c69674dd47"
HEAD_REVISION = "5f048586d8f1"


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(V2_ALEMBIC_DISPOSABLE_TEST, ""),
        }
    )
    if not settings.disposable_test:
        pytest.fail("v2 lifecycle tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


def _config() -> Config:
    return Config(str(REPO / "alembic-v2.ini"))


def _assert_head(engine) -> None:
    assert set(inspect(engine).get_table_names(schema="public")) == (
        EXPECTED_V2_TABLES | {"alembic_version"}
    )
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert context.get_current_revision() == HEAD_REVISION
        assert compare_metadata(context, V2_METADATA) == []
        model_count = connection.execute(
            text(
                "SELECT count(*) FROM public.tax_benefit_models "
                "WHERE name = 'stage8-platform-validation'"
            )
        ).scalar_one()
        version_count = connection.execute(
            text(
                "SELECT count(*) FROM public.tax_benefit_model_versions "
                "WHERE version = 'stage8-platform-validation'"
            )
        ).scalar_one()
    assert (model_count, version_count) == (1, 1)


def test_empty_upgrade_check_boundary_downgrade_and_reupgrade() -> None:
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names(schema="public")) <= {
            "alembic_version"
        }

        command.upgrade(config, "head")
        command.check(config)
        _assert_head(engine)

        command.downgrade(config, BASELINE_REVISION)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() == BASELINE_REVISION
            boundary_drift = compare_metadata(context, V2_METADATA)
            boundary_kinds = [difference[0] for difference in boundary_drift]
            assert boundary_kinds.count("v2_reference_row_change") == 2
            assert boundary_kinds.count("add_fk") == 4
            assert boundary_kinds.count("add_column") == 1
            assert boundary_kinds.count("add_constraint") == 2
            assert len(boundary_kinds) == 9
            model_count = connection.execute(
                text(
                    "SELECT count(*) FROM public.tax_benefit_models "
                    "WHERE name = 'stage8-platform-validation'"
                )
            ).scalar_one()
        assert model_count == 0

        command.upgrade(config, "head")
        command.check(config)
        _assert_head(engine)
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def test_upgrade_to_head_validates_the_resulting_table_inventory() -> None:
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, PREVIOUS_HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE unreviewed_runtime_table (id INT)"))

        with pytest.raises(
            V2MigrationTargetError,
            match="v2 head table inventory.*unreviewed_runtime_table",
        ):
            command.upgrade(config, "head")

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() == PREVIOUS_HEAD_REVISION
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS unreviewed_runtime_table"))
        command.upgrade(config, "head")
        engine.dispose()
