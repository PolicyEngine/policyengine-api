"""Capturing a Cloud Run service's state and promoting exact revisions."""

from __future__ import annotations

import json

import pytest

from tests.unit.cloud_run_deploy_support import (
    STAGING_CLOUD_RUN_SERVICE,
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


def test_capture_cloud_run_service_state_records_stable_url_and_exact_revision(
    tmp_path,
):
    gcloud_path, state_path = _fake_gcloud(tmp_path)

    result = _run_script(
        ".github/scripts/capture_cloud_run_service_state.sh",
        _fake_gcloud_env(gcloud_path, state_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "stable_url=https://policyengine-api.example.test",
        "revision=policyengine-api-00001-old",
    ]


def test_set_cloud_run_revision_promotes_and_rolls_back_exact_revisions(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)
    env = _fake_gcloud_env(gcloud_path, state_path)

    promote = _run_script(
        ".github/scripts/set_cloud_run_revision.sh",
        {
            **env,
            "CLOUD_RUN_TARGET_REVISION": "policyengine-api-00002-new",
            "CLOUD_RUN_EXPECTED_CURRENT_REVISION": "policyengine-api-00001-old",
        },
    )
    rollback = _run_script(
        ".github/scripts/set_cloud_run_revision.sh",
        {
            **env,
            "CLOUD_RUN_TARGET_REVISION": "policyengine-api-00001-old",
            "CLOUD_RUN_EXPECTED_CURRENT_REVISION": "policyengine-api-00002-new",
        },
    )

    assert promote.returncode == 0, promote.stderr
    assert rollback.returncode == 0, rollback.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["active_revision"] == "policyengine-api-00001-old"
    assert state["updates"] == [
        "policyengine-api-00002-new=100",
        "policyengine-api-00001-old=100",
    ]


def test_set_cloud_run_revision_rejects_stale_expected_revision(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)

    result = _run_script(
        ".github/scripts/set_cloud_run_revision.sh",
        {
            **_fake_gcloud_env(gcloud_path, state_path),
            "CLOUD_RUN_TARGET_REVISION": "policyengine-api-00002-new",
            "CLOUD_RUN_EXPECTED_CURRENT_REVISION": "policyengine-api-00000-stale",
        },
    )

    assert result.returncode == 2
    assert "Stable traffic changed after deployment" in result.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["updates"] == []


@pytest.mark.parametrize("revision", ["LATEST", "latest"])
def test_set_cloud_run_revision_rejects_latest_alias(revision):
    result = _run_script(
        ".github/scripts/set_cloud_run_revision.sh",
        _script_env(
            CLOUD_RUN_TARGET_REVISION=revision,
            CLOUD_RUN_EXPECTED_CURRENT_REVISION="policyengine-api-00001-old",
        ),
    )

    assert result.returncode == 2
    assert "must be exact; LATEST is not allowed" in result.stderr


def test_capture_cloud_run_service_state_dry_run_uses_service_url():
    result = _run_script(
        ".github/scripts/capture_cloud_run_service_state.sh",
        _script_env(CLOUD_RUN_SERVICE="policyengine-api"),
    )

    assert result.returncode == 0, result.stderr
    assert "stable_url=https://policyengine-api-dry-run.a.run.app" in result.stdout
    assert "revision=policyengine-api-00001-dry" in result.stdout


def test_set_cloud_run_revision_dry_run_shifts_service_traffic_to_exact_revision():
    result = _run_script(
        ".github/scripts/set_cloud_run_revision.sh",
        _script_env(
            CLOUD_RUN_SERVICE="policyengine-api",
            CLOUD_RUN_TARGET_REVISION="policyengine-api-00002-new",
            CLOUD_RUN_EXPECTED_CURRENT_REVISION="policyengine-api-00001-old",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "gcloud run services update-traffic policyengine-api" in result.stdout
    assert "--to-revisions policyengine-api-00002-new=100" in result.stdout
    assert "--to-tags" not in result.stdout
    assert "--to-latest" not in result.stdout


def test_set_cloud_run_revision_dry_run_targets_service_override():
    result = _run_script(
        ".github/scripts/set_cloud_run_revision.sh",
        _script_env(
            CLOUD_RUN_SERVICE=STAGING_CLOUD_RUN_SERVICE,
            CLOUD_RUN_TARGET_REVISION="policyengine-api-staging-00002-new",
            CLOUD_RUN_EXPECTED_CURRENT_REVISION="policyengine-api-staging-00001-old",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert (
        f"gcloud run services update-traffic {STAGING_CLOUD_RUN_SERVICE}"
        in result.stdout
    )
