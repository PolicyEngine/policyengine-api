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
    DISPOSABLE_DATABASE_NAME,
    MIGRATION_ROLE,
    RECORDED_SUPABASE_TARGETS,
    V2_ALEMBIC_DISPOSABLE_TEST,
    V2AlembicSettings,
    V2MigrationTargetError,
    load_v2_alembic_settings,
    qualify_v2_connection,
    validate_v2_head_table_inventory,
)
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
)
from policyengine_api.data.v2.table_inventory import EXPECTED_V2_TABLES


PROJECT_REF = "kvrifaviwhzjztcbrfpy"
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


def test_persistent_target_requires_the_recorded_environment_and_project() -> None:
    with pytest.raises(V2MigrationTargetError, match="recorded"):
        load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: POOLER_URL,
                V2_SUPABASE_ENVIRONMENT: "production-foundation",
                V2_SUPABASE_PROJECT_REF: "aaaaaaaaaaaaaaaaaaaa",
            }
        )


def test_pooler_identity_resolves_the_recorded_persistent_target() -> None:
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: POOLER_URL,
            V2_SUPABASE_ENVIRONMENT: "production-foundation",
            V2_SUPABASE_PROJECT_REF: PROJECT_REF,
        }
    )

    assert settings.disposable_test is False
    assert settings.target is not None
    assert settings.target.project_ref == PROJECT_REF
    assert settings.url.database == "postgres"


def test_persistent_mode_rejects_an_ambiguous_non_supabase_host() -> None:
    with pytest.raises(V2MigrationTargetError, match="recorded Supabase project"):
        load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: (
                    "postgresql+psycopg://policyengine_v2_migrator:password@"
                    "db.example.com/postgres?sslmode=require"
                ),
                V2_SUPABASE_ENVIRONMENT: "production-foundation",
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


def test_v2_environment_loads_only_the_exact_sqlmodel_inventory() -> None:
    env_source = (REPO / "migrations" / "v2" / "env.py").read_text(encoding="utf-8")

    assert V2_METADATA is not V1Base.metadata
    assert set(V2_METADATA.tables) == EXPECTED_V2_TABLES
    assert "V1Base" not in env_source
    assert "migrations/v1" not in env_source
    assert "validate_v2_table_inventory" in env_source


def test_v2_files_are_mechanically_separate_from_v1() -> None:
    v2_files = {
        path.relative_to(REPO)
        for path in (REPO / "migrations" / "v2").rglob("*")
        if path.is_file()
    }

    assert Path("migrations/v2/env.py") in v2_files
    assert Path("migrations/v2/script.py.mako") in v2_files
    assert all("migrations/v1" not in str(path) for path in v2_files)


def test_v2_revision_chain_is_linear_generated_and_correction_bounded() -> None:
    config = Config(str(REPO / "alembic-v2.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["5f048586d8f1"]
    assert [revision.revision for revision in script.walk_revisions()] == [
        "5f048586d8f1",
        "b4c69674dd47",
        "6ee725e0c563",
        "47592781336f",
    ]

    baseline = (
        REPO
        / "migrations/v2/versions/47592781336f_establish_v2_core_schema_baseline.py"
    ).read_text(encoding="utf-8")
    data = (
        REPO
        / "migrations/v2/versions/6ee725e0c563_add_stage_8_platform_validation_data.py"
    ).read_text(encoding="utf-8")
    ownership = (
        REPO / "migrations/v2/versions/"
        "b4c69674dd47_enforce_v2_user_association_ownership.py"
    ).read_text(encoding="utf-8")
    constraints = (
        REPO
        / "migrations/v2/versions/5f048586d8f1_constrain_v2_user_country_and_report_.py"
    ).read_text(encoding="utf-8")
    revisions = baseline + data + ownership + constraints
    assert all(
        "Generation: uv run alembic -c alembic-v2.ini revision --autogenerate" in source
        for source in (baseline, data, ownership, constraints)
    )
    assert "op.execute(" not in revisions
    assert "op.bulk_insert(" not in revisions
    assert data.count("op.v2_reference_row_change(") == 4
    assert "op.create_table(" not in data
    assert "op.drop_table(" not in data
    assert ownership.count("op.create_foreign_key(") == 4
    assert ownership.count("op.drop_constraint(") == 4
    assert 'ondelete="CASCADE"' in ownership
    assert constraints.count("op.add_column(") == 1
    assert constraints.count("op.create_check_constraint(") == 2
    assert "ck_users_primary_country" in constraints
    assert "ck_report_runs_idempotency_key_nonblank" in constraints

    corrected_enum_names = set(
        re.findall(
            r"sa\.Enum\(name=[\"']([^\"']+)[\"']\)\.drop\(op\.get_bind\(\)\)",
            revisions,
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


def test_alembic_rejects_unknown_missing_and_divergent_history(tmp_path: Path) -> None:
    original = REPO / "migrations/v2"
    missing = tmp_path / "missing"
    shutil.copytree(original, missing)
    (missing / "versions/47592781336f_establish_v2_core_schema_baseline.py").unlink()
    missing_config = Config()
    missing_config.set_main_option("script_location", str(missing))
    with pytest.raises((KeyError, ResolutionError)):
        list(ScriptDirectory.from_config(missing_config).walk_revisions())

    divergent = tmp_path / "divergent"
    shutil.copytree(original, divergent)
    source = divergent / "versions/6ee725e0c563_add_stage_8_platform_validation_data.py"
    duplicate = source.read_text(encoding="utf-8").replace(
        "6ee725e0c563", "aaaaaaaaaaaa"
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


def test_persistent_first_use_requires_recorded_successful_freshness_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = RECORDED_SUPABASE_TARGETS["production-foundation"]
    unaudited = target.__class__(
        environment=target.environment,
        project_ref=target.project_ref,
        database_name=target.database_name,
        migration_role=target.migration_role,
        freshness_audited_on=target.freshness_audited_on,
        freshness_audit_passed=False,
    )
    settings = V2AlembicSettings(
        url=load_v2_alembic_settings(
            {
                V2_MIGRATION_DATABASE_URL: POOLER_URL,
                V2_SUPABASE_ENVIRONMENT: "production-foundation",
                V2_SUPABASE_PROJECT_REF: PROJECT_REF,
            }
        ).url,
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
            V2_SUPABASE_ENVIRONMENT: "production-foundation",
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
            V2_SUPABASE_ENVIRONMENT: "production-foundation",
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
        {"alembic_version", *EXPECTED_V2_TABLES, "runtime_bundles"},
    ],
)
def test_v2_head_rejects_divergent_table_inventory(
    monkeypatch: pytest.MonkeyPatch,
    public_tables: set[str],
) -> None:
    connection = _persistent_connection(
        monkeypatch,
        public_tables=public_tables,
    )

    with pytest.raises(V2MigrationTargetError, match="v2 head table inventory"):
        validate_v2_head_table_inventory(connection)


def test_v2_head_accepts_exact_table_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _persistent_connection(
        monkeypatch,
        public_tables={"alembic_version", *EXPECTED_V2_TABLES},
    )

    validate_v2_head_table_inventory(connection)


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
    assert "validate_v2_head_table_inventory(connection)" in env_source
