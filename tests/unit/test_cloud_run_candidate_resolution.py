"""Resolving a deployed Cloud Run candidate and checking what it runs."""

from __future__ import annotations

import json

from tests.unit.cloud_run_deploy_support import (
    PRODUCTION_CLOUD_SQL_INSTANCE,
)
from tests.unit.cloud_run_deploy_support import (
    fake_gcloud as _fake_gcloud,
)
from tests.unit.cloud_run_deploy_support import (
    fake_gcloud_env as _fake_gcloud_env,
)
from tests.unit.cloud_run_deploy_support import (
    run_script as _run_script,
)
from tests.unit.cloud_run_deploy_support import (
    script_env as _script_env,
)
from tests.unit.cloud_run_deploy_support import (
    v2_target_env as _v2_target_env,
)


def test_resolve_cloud_run_candidate_records_exact_ready_revision_and_image(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        _fake_gcloud_env(gcloud_path, state_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "url=https://stage3-test.example.test",
        "revision=policyengine-api-00002-new",
        ("image=us-central1-docker.pkg.dev/project/repo/api@sha256:candidate"),
    ]


def test_resolve_cloud_run_candidate_rejects_wrong_hugging_face_secret(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_secret_env"]["HUGGING_FACE_TOKEN"]["name"] = (
        "policyengine-api-prod-hugging-face-token"
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        _fake_gcloud_env(gcloud_path, state_path),
    )

    assert result.returncode == 2
    assert "binds HUGGING_FACE_TOKEN" in result.stderr
    assert "expected pe-uk-private-hf-read-token:latest" in result.stderr


def test_resolve_cloud_run_candidate_rejects_changed_revision(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        {
            **_fake_gcloud_env(gcloud_path, state_path),
            "CLOUD_RUN_EXPECTED_REVISION": "policyengine-api-00003-unexpected",
            "CLOUD_RUN_EXPECTED_IMAGE": (
                "us-central1-docker.pkg.dev/project/repo/api@sha256:candidate"
            ),
        },
    )

    assert result.returncode == 2
    assert "Candidate tag stage3-test moved" in result.stderr


def test_resolve_cloud_run_candidate_rejects_changed_image(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        {
            **_fake_gcloud_env(gcloud_path, state_path),
            "CLOUD_RUN_EXPECTED_REVISION": "policyengine-api-00002-new",
            "CLOUD_RUN_EXPECTED_IMAGE": (
                "us-central1-docker.pkg.dev/project/repo/api@sha256:unexpected"
            ),
        },
    )

    assert result.returncode == 2
    assert "Candidate image changed" in result.stderr


def test_resolve_cloud_run_candidate_verifies_deployment_selectors(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)
    env = {
        **_fake_gcloud_env(gcloud_path, state_path),
        "ROUTE_IMPL_HEALTH": "fastapi_native",
        "ROUTE_IMPL_SPECIFICATION": "fastapi_native",
        "ROUTE_IMPL_METADATA": "fastapi_native",
        "ROUTE_IMPL_POLICY": "flask_fallback",
        "ROUTE_IMPL_HOUSEHOLD": "flask_fallback",
        "DB_READ_POLICY": "cloud_sql",
        "DB_WRITE_POLICY": "cloud_sql",
        "DB_READ_HOUSEHOLD": "cloud_sql",
        "DB_WRITE_HOUSEHOLD": "cloud_sql",
    }

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        env,
    )

    assert result.returncode == 0, result.stderr


def test_resolve_cloud_run_candidate_rejects_deployment_selector_mismatch(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_env"]["ROUTE_IMPL_METADATA"] = "flask_fallback"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        {
            **_fake_gcloud_env(gcloud_path, state_path),
            "ROUTE_IMPL_HEALTH": "fastapi_native",
            "ROUTE_IMPL_SPECIFICATION": "fastapi_native",
            "ROUTE_IMPL_METADATA": "fastapi_native",
            "ROUTE_IMPL_POLICY": "flask_fallback",
            "ROUTE_IMPL_HOUSEHOLD": "flask_fallback",
            "DB_READ_POLICY": "cloud_sql",
            "DB_WRITE_POLICY": "cloud_sql",
            "DB_READ_HOUSEHOLD": "cloud_sql",
            "DB_WRITE_HOUSEHOLD": "cloud_sql",
        },
    )

    assert result.returncode == 2
    assert (
        "Revision policyengine-api-00002-new has ROUTE_IMPL_METADATA="
        "flask_fallback; expected fastapi_native"
    ) in result.stderr


def test_resolve_cloud_run_candidate_rejects_policy_write_selector_mismatch(
    tmp_path,
):
    gcloud_path, state_path = _fake_gcloud(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_env"]["DB_WRITE_POLICY"] = "dual_write"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        {
            **_fake_gcloud_env(gcloud_path, state_path),
            "ROUTE_IMPL_HEALTH": "fastapi_native",
            "ROUTE_IMPL_SPECIFICATION": "fastapi_native",
            "ROUTE_IMPL_METADATA": "fastapi_native",
            "ROUTE_IMPL_POLICY": "flask_fallback",
            "ROUTE_IMPL_HOUSEHOLD": "flask_fallback",
            "DB_READ_POLICY": "cloud_sql",
            "DB_WRITE_POLICY": "cloud_sql",
            "DB_READ_HOUSEHOLD": "cloud_sql",
            "DB_WRITE_HOUSEHOLD": "cloud_sql",
        },
    )

    assert result.returncode == 2
    assert (
        "Revision policyengine-api-00002-new has DB_WRITE_POLICY=dual_write; "
        "expected cloud_sql"
    ) in result.stderr


def test_resolve_cloud_run_candidate_verifies_database_identities(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        {
            **_fake_gcloud_env(gcloud_path, state_path),
            **_v2_target_env(),
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (PRODUCTION_CLOUD_SQL_INSTANCE),
        },
    )

    assert result.returncode == 0, result.stderr


def test_resolve_cloud_run_candidate_rejects_database_identity_mismatch(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_env"]["V2_SUPABASE_PROJECT_REF"] = "z" * 20
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        {
            **_fake_gcloud_env(gcloud_path, state_path),
            **_v2_target_env(),
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (PRODUCTION_CLOUD_SQL_INSTANCE),
        },
    )

    assert result.returncode == 2
    assert "V2_SUPABASE_PROJECT_REF=zzzz" in result.stderr


def test_resolve_cloud_run_candidate_rejects_cloud_sql_attachment_mismatch(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_cloud_sql"] = "project:region:wrong-instance"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        {
            **_fake_gcloud_env(gcloud_path, state_path),
            **_v2_target_env(),
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (PRODUCTION_CLOUD_SQL_INSTANCE),
        },
    )

    assert result.returncode == 2
    assert "attaches Cloud SQL instance project:region:wrong-instance" in result.stderr


def test_resolve_cloud_run_candidate_state_dry_run_uses_candidate_tag():
    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        _script_env(CLOUD_RUN_TAG="stage3-test", CLOUD_RUN_SERVICE="policyengine-api"),
    )

    assert result.returncode == 0, result.stderr
    assert (
        "url=https://stage3-test---policyengine-api-dry-run.a.run.app" in result.stdout
    )
    assert "revision=policyengine-api-00002-dry" in result.stdout
    assert "@sha256:dry-run" in result.stdout
