"""Unit guards for the isolated and qualified v2 Alembic environment."""

from io import StringIO
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from alembic.util import CommandError
import pytest

from policyengine_api.constants import REPO
from policyengine_api.data.v1_models import V1Base
from policyengine_api.data.v2.migration_target import (
    ConfiguredSupabaseTarget,
    DISPOSABLE_DATABASE_NAME,
    MIGRATION_ROLE,
    V2_ALEMBIC_DISPOSABLE_TEST,
    V2AlembicSettings,
    V2MigrationTargetError,
    load_v2_alembic_settings,
    qualify_v2_connection,
    validate_v2_head_schema,
)
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
)

PROJECT_REF = "abcdefghijklmnopqrst"
TARGET_ENVIRONMENT = "test-foundation"
V2_TABLE_NAMES = frozenset(table.name for table in V2_METADATA.tables.values())
POOLER_URL = (
    "postgresql+psycopg://policyengine_v2_migrator."
    f"{PROJECT_REF}:test-password@aws-0-us-east-2.pooler.supabase.com:5432/"
    "postgres?sslmode=require"
)
DISPOSABLE_URL = (
    "postgresql+psycopg://postgres:test-password@127.0.0.1:5432/"
    f"{DISPOSABLE_DATABASE_NAME}"
)


def _clear_v2_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        V2_MIGRATION_DATABASE_URL,
        V2_ALEMBIC_DISPOSABLE_TEST,
        V2_SUPABASE_ENVIRONMENT,
        V2_SUPABASE_PROJECT_REF,
        "ALEMBIC_DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_v2_configuration_contains_no_database_url() -> None:
    config_text = (REPO / "alembic-v2.ini").read_text(encoding="utf-8")

    assert "sqlalchemy.url" not in config_text
    assert "migrations/v2" in config_text


def test_v2_alembic_requires_its_explicit_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_v2_environment(monkeypatch)
    monkeypatch.setenv(
        "ALEMBIC_DATABASE_URL",
        "mysql+pymysql://v1:test-password@localhost/v1",
    )
    config = Config(str(REPO / "alembic-v2.ini"), output_buffer=StringIO())

    with pytest.raises(V2MigrationTargetError, match=V2_MIGRATION_DATABASE_URL):
        command.upgrade(config, "head", sql=True)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+pysqlite:///:memory:",
        "mysql+pymysql://user:password@localhost/database",
        "postgresql+asyncpg://user:password@localhost/database",
    ],
)
def test_v2_alembic_rejects_non_psycopg_postgres_urls(url: str) -> None:
    with pytest.raises(V2MigrationTargetError, match=r"postgresql\+psycopg"):
        load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: url,
                V2_ALEMBIC_DISPOSABLE_TEST: "1",
            }
        )


def test_disposable_mode_requires_the_exact_isolated_local_database() -> None:
    with pytest.raises(V2MigrationTargetError, match=DISPOSABLE_DATABASE_NAME):
        load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: (
                    "postgresql+psycopg://postgres:password@127.0.0.1/postgres"
                ),
                V2_ALEMBIC_DISPOSABLE_TEST: "1",
            }
        )


def test_disposable_mode_cannot_target_supabase() -> None:
    with pytest.raises(V2MigrationTargetError, match="isolated local"):
        load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: POOLER_URL,
                V2_ALEMBIC_DISPOSABLE_TEST: "1",
            }
        )


def test_v2_alembic_rejects_offline_execution_even_in_disposable_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_v2_environment(monkeypatch)
    monkeypatch.setenv(V2_MIGRATION_DATABASE_URL, DISPOSABLE_URL)
    monkeypatch.setenv(V2_ALEMBIC_DISPOSABLE_TEST, "1")
    config = Config(str(REPO / "alembic-v2.ini"), output_buffer=StringIO())

    with pytest.raises(RuntimeError, match="online connection"):
        command.upgrade(config, "head", sql=True)


def test_persistent_target_requires_the_configured_project_to_match_the_url() -> None:
    with pytest.raises(V2MigrationTargetError, match="configured Supabase project"):
        load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: POOLER_URL,
                V2_SUPABASE_ENVIRONMENT: TARGET_ENVIRONMENT,
                V2_SUPABASE_PROJECT_REF: "aaaaaaaaaaaaaaaaaaaa",
            }
        )


def test_pooler_identity_resolves_the_configured_persistent_target() -> None:
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: POOLER_URL,
            V2_SUPABASE_ENVIRONMENT: TARGET_ENVIRONMENT,
            V2_SUPABASE_PROJECT_REF: PROJECT_REF,
        }
    )

    assert settings.disposable_test is False
    assert settings.target is not None
    assert settings.target.project_ref == PROJECT_REF
    assert settings.url.database == "postgres"


def test_persistent_mode_rejects_an_ambiguous_non_supabase_host() -> None:
    with pytest.raises(V2MigrationTargetError, match="configured Supabase project"):
        load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: (
                    "postgresql+psycopg://policyengine_v2_migrator:password@"
                    "db.example.com/postgres?sslmode=require"
                ),
                V2_SUPABASE_ENVIRONMENT: TARGET_ENVIRONMENT,
                V2_SUPABASE_PROJECT_REF: PROJECT_REF,
            }
        )


def test_target_errors_never_echo_url_passwords() -> None:
    secret = "do-not-echo-this-password"
    with pytest.raises(V2MigrationTargetError) as raised:
        load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: (
                    f"postgresql+psycopg://user:{secret}@localhost/postgres"
                ),
                V2_ALEMBIC_DISPOSABLE_TEST: "1",
            }
        )

    assert secret not in str(raised.value)


def test_v2_environment_uses_only_sqlmodel_metadata() -> None:
    env_source = (REPO / "migrations" / "v2" / "env.py").read_text(encoding="utf-8")

    assert V2_METADATA is not V1Base.metadata
    assert V2_TABLE_NAMES
    assert "V1Base" not in env_source
    assert "migrations/v1" not in env_source
    assert "historical_reference_data_operations" not in env_source
    assert "reference_data_autogenerate" not in env_source
    assert not (
        REPO / "policyengine_api/data/v2/historical_reference_data_operations.py"
    ).exists()
    assert not (REPO / "policyengine_api/data/v2/reference_data.py").exists()
    assert not (
        REPO / "policyengine_api/data/v2/reference_data_autogenerate.py"
    ).exists()


def test_v2_files_are_mechanically_separate_from_v1() -> None:
    v2_files = {
        path.relative_to(REPO)
        for path in (REPO / "migrations" / "v2").rglob("*")
        if path.is_file()
    }

    assert Path("migrations/v2/env.py") in v2_files
    assert Path("migrations/v2/script.py.mako") in v2_files
    assert all("migrations/v1" not in str(path) for path in v2_files)


def test_v2_revision_chain_has_generated_policy_and_user_identity_changes() -> None:
    config = Config(str(REPO / "alembic-v2.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["af34023a728f"]
    assert [revision.revision for revision in script.walk_revisions()] == [
        "af34023a728f",
        "c21c4a807a49",
        "711ec2f0a5a5",
        "68b4a5ae5dc5",
        "f5ef4347cb2a",
    ]

    baseline = (
        REPO / "migrations/v2/versions/f5ef4347cb2a_establish_v2_platform_baseline.py"
    ).read_text(encoding="utf-8")
    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in baseline
    )
    assert "down_revision: Union[str, None] = None" in baseline
    assert "op.execute(" not in baseline
    assert "op.bulk_insert(" not in baseline
    assert "op.v2_reference_row_change(" not in baseline
    assert "region_datasets" not in baseline
    assert "historical_reference_data_operations" not in baseline
    assert "ck_users_primary_country" in baseline
    assert "ck_report_runs_idempotency_key_nonblank" not in baseline
    assert re.search(
        r'sa\.Column\(\s*"idempotency_key",\s*sa\.Uuid\(\)',
        baseline,
    )
    assert "fk_regions_default_dataset_model_datasets" in baseline
    assert "uq_datasets_model_name" in baseline
    assert "ck_datasets_output_storage_path" in baseline
    assert baseline.count("op.create_table(") == len(V2_TABLE_NAMES) - 3
    assert baseline.count("op.drop_table(") == len(V2_TABLE_NAMES) - 3

    corrected_enum_names = set(
        re.findall(
            r"sa\.Enum\(name=[\"']([^\"']+)[\"']\)\.drop\(op\.get_bind\(\)\)",
            baseline,
        )
    )
    assert corrected_enum_names == {
        "v2_aggregate_type",
        "v2_decile_type",
        "v2_household_job_status",
        "v2_output_status",
        "v2_region_type",
        "v2_report_run_status",
        "v2_report_run_trigger",
        "v2_simulation_status",
        "v2_simulation_type",
    }

    stage_9_revision = (
        REPO
        / "migrations/v2/versions/68b4a5ae5dc5_version_metadata_catalog_snapshots.py"
    ).read_text(encoding="utf-8")
    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in stage_9_revision
    )
    assert 'down_revision: Union[str, None] = "f5ef4347cb2a"' in stage_9_revision
    assert "uq_parameter_values_canonical_parameter_start_date" in stage_9_revision
    assert "op.create_index(" in stage_9_revision
    assert "op.drop_index(" in stage_9_revision
    assert "tax_benefit_model_version_id" in stage_9_revision
    assert "metadata_time_periods" in stage_9_revision
    assert "current_law_id" in stage_9_revision
    assert "op.execute(" not in stage_9_revision
    assert "op.bulk_insert(" not in stage_9_revision


def test_phase_10_revision_has_only_documented_generation_corrections() -> None:
    revision = (
        REPO / "migrations/v2/versions/711ec2f0a5a5_migrate_v2_policies.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "68b4a5ae5dc5"' in revision
    assert revision.count("Post-generation correction:") == 4
    assert 'postgresql_using="user_id::text"' in revision
    assert 'postgresql_using="user_id::uuid"' in revision
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision

    policy_key = revision.index('"uq_policies_id_country"')
    policy_mapping = revision.index(
        'op.create_table(\n        "legacy_policy_mappings"'
    )
    association_key = revision.index('"uq_user_policies_id_country"')
    association_mapping = revision.index(
        'op.create_table(\n        "legacy_user_policy_mappings"'
    )
    drop_association_mapping = revision.index(
        'op.drop_table("legacy_user_policy_mappings")'
    )
    drop_association_key = revision.index(
        'op.drop_constraint("uq_user_policies_id_country"'
    )

    assert policy_key < policy_mapping
    assert association_key < association_mapping
    assert drop_association_mapping < drop_association_key


def test_saved_policy_revision_tracking_was_generated_after_phase_10() -> None:
    revision = (
        REPO
        / "migrations/v2/versions/c21c4a807a49_track_saved_policy_mirror_revisions.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "711ec2f0a5a5"' in revision
    assert "last_applied_source_revision" in revision
    assert "ck_legacy_user_policy_mappings_source_revision" in revision
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_legacy_user_uuid_mapping_revision_is_generated_and_reversible() -> None:
    revision = (
        REPO / "migrations/v2/versions/af34023a728f_map_legacy_users_to_v2_uuids.py"
    ).read_text(encoding="utf-8")

    assert (
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate"
        in revision
    )
    assert 'down_revision: Union[str, None] = "c21c4a807a49"' in revision
    assert revision.count("Post-generation correction:") == 2
    assert 'postgresql_using="user_id::uuid"' in revision
    assert 'postgresql_using="user_id::text"' in revision
    assert 'op.create_table(\n        "legacy_user_mappings"' in revision
    assert 'op.drop_table("legacy_user_mappings")' in revision
    assert "fk_user_policies_user_id_users" in revision
    assert "uq_legacy_user_mappings_user_id" in revision
    assert "op.execute(" not in revision
    assert "op.bulk_insert(" not in revision


def test_alembic_rejects_unknown_missing_and_divergent_history(tmp_path: Path) -> None:
    original = REPO / "migrations/v2"
    missing = tmp_path / "missing"
    shutil.copytree(original, missing)
    (missing / "versions/f5ef4347cb2a_establish_v2_platform_baseline.py").unlink()
    missing_config = Config()
    missing_config.set_main_option("script_location", str(missing))
    with pytest.warns(UserWarning, match=r"Revision f5ef4347cb2a .* is not present"):
        missing_script = ScriptDirectory.from_config(missing_config)
        with pytest.raises((CommandError, KeyError, ResolutionError)):
            missing_script.get_revision("f5ef4347cb2a")

    divergent = tmp_path / "divergent"
    shutil.copytree(original, divergent)
    source = divergent / "versions/f5ef4347cb2a_establish_v2_platform_baseline.py"
    duplicate = source.read_text(encoding="utf-8").replace(
        "f5ef4347cb2a", "aaaaaaaaaaaa"
    )
    (divergent / "versions/aaaaaaaaaaaa_divergent.py").write_text(
        duplicate,
        encoding="utf-8",
    )
    divergent_config = Config()
    divergent_config.set_main_option("script_location", str(divergent))
    divergent_script = ScriptDirectory.from_config(divergent_config)
    with pytest.raises(CommandError, match="multiple heads"):
        divergent_script.get_current_head()
    with pytest.raises((CommandError, ResolutionError)):
        divergent_script.get_revision("bbbbbbbbbbbb")


def _persistent_connection(
    monkeypatch: pytest.MonkeyPatch,
    *,
    public_tables: set[str],
):
    import policyengine_api.data.v2.migration_target as module

    connection = MagicMock()
    connection.dialect.name = "postgresql"
    connection.execute.side_effect = [
        SimpleNamespace(one=lambda: ("postgres", MIGRATION_ROLE)),
        SimpleNamespace(scalar_one=lambda: True),
    ]
    monkeypatch.setattr(
        module,
        "inspect",
        lambda _: SimpleNamespace(get_table_names=lambda schema: list(public_tables)),
    )
    return connection


def test_persistent_first_use_requires_configured_successful_freshness_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: POOLER_URL,
            V2_SUPABASE_ENVIRONMENT: TARGET_ENVIRONMENT,
            V2_SUPABASE_PROJECT_REF: PROJECT_REF,
        }
    )
    assert configured.target is not None
    unaudited = ConfiguredSupabaseTarget(
        environment=configured.target.environment,
        project_ref=configured.target.project_ref,
        database_name=configured.target.database_name,
        migration_role=configured.target.migration_role,
        freshness_audited_on=configured.target.freshness_audited_on,
        freshness_audit_passed=False,
    )
    settings = V2AlembicSettings(
        url=configured.url,
        disposable_test=False,
        target=unaudited,
    )

    with pytest.raises(V2MigrationTargetError, match="freshness audit"):
        qualify_v2_connection(
            _persistent_connection(monkeypatch, public_tables=set()),
            settings,
        )


def test_persistent_target_rejects_unstamped_nonfresh_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: POOLER_URL,
            V2_SUPABASE_ENVIRONMENT: TARGET_ENVIRONMENT,
            V2_SUPABASE_PROJECT_REF: PROJECT_REF,
        }
    )

    with pytest.raises(V2MigrationTargetError):
        qualify_v2_connection(
            _persistent_connection(
                monkeypatch,
                public_tables={"unreviewed_predecessor"},
            ),
            settings,
        )


def test_persistent_target_allows_stamped_previous_revision_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: POOLER_URL,
            V2_SUPABASE_ENVIRONMENT: TARGET_ENVIRONMENT,
            V2_SUPABASE_PROJECT_REF: PROJECT_REF,
        }
    )

    qualify_v2_connection(
        _persistent_connection(
            monkeypatch,
            public_tables={"alembic_version", "reports"},
        ),
        settings,
    )


@pytest.mark.parametrize(
    "public_tables",
    [
        {"alembic_version", "reports"},
        {"alembic_version", *V2_TABLE_NAMES, "runtime_bundles"},
    ],
)
def test_v2_head_rejects_schema_divergent_from_metadata(
    monkeypatch: pytest.MonkeyPatch,
    public_tables: set[str],
) -> None:
    connection = _persistent_connection(
        monkeypatch,
        public_tables=public_tables,
    )

    with pytest.raises(V2MigrationTargetError, match="v2 head schema"):
        validate_v2_head_schema(connection, V2_METADATA)


def test_v2_head_accepts_schema_matching_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _persistent_connection(
        monkeypatch,
        public_tables={"alembic_version", *V2_TABLE_NAMES},
    )

    validate_v2_head_schema(connection, V2_METADATA)


def test_v2_environment_contains_no_reset_adopt_or_restamp_path() -> None:
    env_source = (REPO / "migrations/v2/env.py").read_text(encoding="utf-8")
    assert "create_all" not in env_source
    assert "command.stamp" not in env_source
    assert "drop_all" not in env_source
    assert "DROP SCHEMA" not in env_source


def test_v2_environment_commits_after_persistent_target_qualification() -> None:
    env_source = (REPO / "migrations/v2/env.py").read_text(encoding="utf-8")

    assert "with engine.begin() as connection:" in env_source
    assert "with engine.connect() as connection:" not in env_source
    assert "current_heads != previous_heads" in env_source
    assert "current_heads == script_heads" in env_source
    assert "validate_v2_head_schema(connection, target_metadata)" in env_source
