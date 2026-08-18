"""Exercise the isolated v2 Alembic lifecycle against disposable Postgres."""

import os
from uuid import UUID, uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID

from policyengine_api.constants import REPO
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    V2MigrationTargetError,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.data.v2.table_inventory import EXPECTED_V2_TABLES


HEAD_REVISION = "f5ef4347cb2a"


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
    assert (model_count, version_count) == (0, 0)


def test_empty_upgrade_check_base_downgrade_and_reupgrade() -> None:
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

        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names(schema="public")) <= {
            "alembic_version"
        }
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() is None
            remaining_enum_count = connection.execute(
                text(
                    "SELECT count(*) FROM pg_type "
                    "WHERE typname LIKE 'v2_%' AND typtype = 'e'"
                )
            ).scalar_one()
        assert remaining_enum_count == 0

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
        command.downgrade(config, "base")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE unreviewed_runtime_table (id INT)"))

        with pytest.raises(
            V2MigrationTargetError,
            match="v2 head table inventory.*unreviewed_runtime_table",
        ):
            command.upgrade(config, "head")

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() is None
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS unreviewed_runtime_table"))
        command.upgrade(config, "head")
        engine.dispose()


def test_baseline_uses_native_uuid_report_run_idempotency() -> None:
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)

    def idempotency_column_type():
        return next(
            column["type"]
            for column in inspect(engine).get_columns("report_runs")
            if column["name"] == "idempotency_key"
        )

    def report_run_checks() -> set[str]:
        return {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints("report_runs")
        }

    try:
        command.upgrade(config, "head")
        assert isinstance(idempotency_column_type(), PostgresUUID)
        assert "ck_report_runs_idempotency_key_nonblank" not in report_run_checks()

        model_id = uuid4()
        report_id = uuid4()
        report_run_id = uuid4()
        request_key = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO tax_benefit_models (id, name) VALUES (:id, :name)"),
                {"id": model_id, "name": f"uuid-cast-{model_id.hex[:8]}"},
            )
            connection.execute(
                text(
                    "INSERT INTO reports "
                    "(id, label, country, tax_benefit_model_id, inputs) "
                    "VALUES (:id, 'UUID cast report', 'us', :model_id, '{}')"
                ),
                {"id": report_id, "model_id": model_id},
            )
            connection.execute(
                text(
                    "INSERT INTO report_runs "
                    "(id, report_id, country_package_version, "
                    "policyengine_version, status, trigger, idempotency_key) "
                    "VALUES (:id, :report_id, '1.0', '1.0', 'pending', "
                    "'manual', :request_key)"
                ),
                {
                    "id": report_run_id,
                    "report_id": report_id,
                    "request_key": str(request_key),
                },
            )

        with engine.connect() as connection:
            stored_key = connection.execute(
                text("SELECT idempotency_key FROM report_runs WHERE id = :run_id"),
                {"run_id": report_run_id},
            ).scalar_one()
        assert stored_key == request_key
        assert isinstance(stored_key, UUID)
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM report_runs WHERE id = :run_id"),
                {"run_id": report_run_id},
            )
            connection.execute(
                text("DELETE FROM reports WHERE id = :report_id"),
                {"report_id": report_id},
            )
            connection.execute(
                text("DELETE FROM tax_benefit_models WHERE id = :model_id"),
                {"model_id": model_id},
            )
        command.upgrade(config, "head")
        engine.dispose()


def test_baseline_region_default_enforces_same_model_dataset() -> None:
    database_url = _disposable_url()
    config = _config()
    engine = create_engine(database_url)
    first_model_id = uuid4()
    second_model_id = uuid4()
    first_dataset_id = uuid4()
    second_dataset_id = uuid4()

    try:
        command.upgrade(config, "head")
        assert "region_datasets" not in inspect(engine).get_table_names(schema="public")
        default_column = next(
            column
            for column in inspect(engine).get_columns("regions")
            if column["name"] == "default_dataset_id"
        )
        assert not default_column["nullable"]
        default_constraint = next(
            constraint
            for constraint in inspect(engine).get_foreign_keys("regions")
            if constraint["name"] == "fk_regions_default_dataset_model_datasets"
        )
        assert default_constraint["constrained_columns"] == [
            "default_dataset_id",
            "tax_benefit_model_id",
        ]
        assert default_constraint["referred_columns"] == [
            "id",
            "tax_benefit_model_id",
        ]

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tax_benefit_models (id, name) "
                    "VALUES (:first_id, :first_name), (:second_id, :second_name)"
                ),
                {
                    "first_id": first_model_id,
                    "first_name": f"region-default-{first_model_id.hex[:8]}",
                    "second_id": second_model_id,
                    "second_name": f"region-default-{second_model_id.hex[:8]}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO datasets "
                    "(id, name, year, is_output_dataset, tax_benefit_model_id) "
                    "VALUES (:first_id, 'logical-input', 2024, false, :first_model), "
                    "(:second_id, 'logical-input', 2024, false, :second_model)"
                ),
                {
                    "first_id": first_dataset_id,
                    "first_model": first_model_id,
                    "second_id": second_dataset_id,
                    "second_model": second_model_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO regions "
                    "(id, code, label, region_type, requires_filter, "
                    "tax_benefit_model_id, default_dataset_id) "
                    "VALUES (:id, 'us', 'United States', 'national', false, "
                    ":model_id, :dataset_id)"
                ),
                {
                    "id": uuid4(),
                    "model_id": first_model_id,
                    "dataset_id": first_dataset_id,
                },
            )

        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO regions "
                        "(id, code, label, region_type, requires_filter, "
                        "tax_benefit_model_id, default_dataset_id) "
                        "VALUES (:id, 'state/ca', 'California', 'state', false, "
                        ":model_id, :dataset_id)"
                    ),
                    {
                        "id": uuid4(),
                        "model_id": first_model_id,
                        "dataset_id": second_dataset_id,
                    },
                )

        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO datasets "
                        "(id, name, year, is_output_dataset, "
                        "tax_benefit_model_id) "
                        "VALUES (:id, 'missing-output-path', 2024, true, :model_id)"
                    ),
                    {"id": uuid4(), "model_id": first_model_id},
                )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM regions WHERE tax_benefit_model_id IN (:a, :b)"),
                {"a": first_model_id, "b": second_model_id},
            )
            connection.execute(
                text("DELETE FROM datasets WHERE tax_benefit_model_id IN (:a, :b)"),
                {"a": first_model_id, "b": second_model_id},
            )
            connection.execute(
                text("DELETE FROM tax_benefit_models WHERE id IN (:a, :b)"),
                {"a": first_model_id, "b": second_model_id},
            )
        command.upgrade(config, "head")
        engine.dispose()
