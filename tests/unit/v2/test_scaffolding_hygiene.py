"""Tests for the staged one-off Supabase artifact guard."""

from scripts.check_stage8_scaffolding_hygiene import prohibited_staged_paths


def test_rejects_one_off_supabase_and_secret_shaped_artifacts() -> None:
    assert prohibited_staged_paths(
        [
            "supabase/.temp/project-ref",
            ".agent-artifacts/stage8/bootstrap.json",
            "tmp/stage8-scratch.sql",
            "config/.env",
            "private/storage-admin.key",
            "scripts/one-off-supabase.py",
            "scripts/bootstrap_v2_supabase_storage.py",
            "policyengine_api/data/v2/storage_bootstrap.py",
            "tests/unit/v2/test_storage_bootstrap.py",
            "docs/migration/stage-8-supabase-bootstrap.md",
        ]
    ) == [
        ".agent-artifacts/stage8/bootstrap.json",
        "config/.env",
        "docs/migration/stage-8-supabase-bootstrap.md",
        "policyengine_api/data/v2/storage_bootstrap.py",
        "private/storage-admin.key",
        "scripts/bootstrap_v2_supabase_storage.py",
        "scripts/one-off-supabase.py",
        "supabase/.temp/project-ref",
        "tests/unit/v2/test_storage_bootstrap.py",
        "tmp/stage8-scratch.sql",
    ]


def test_allows_durable_migrations_hygiene_checks_and_docs() -> None:
    assert (
        prohibited_staged_paths(
            [
                "migrations/v2/versions/abc_generated.py",
                "scripts/check_stage8_scaffolding_hygiene.py",
                "tests/unit/v2/test_scaffolding_hygiene.py",
                "docs/migration/stage-8-platform-runbook.md",
                ".env.example",
            ]
        )
        == []
    )
