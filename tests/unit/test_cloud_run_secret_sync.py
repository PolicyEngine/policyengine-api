"""Syncing Cloud Run secrets: the manual workflow and its script."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.cloud_run_deploy_support import (
    PRODUCTION_CLOUD_RUN_SERVICE,
    PRODUCTION_DB_PASSWORD_SECRET,
    REPO,
    STAGING_CLOUD_RUN_SERVICE,
)
from tests.unit.cloud_run_deploy_support import (
    pr_workflow as _pr_workflow,
)
from tests.unit.cloud_run_deploy_support import (
    push_workflow as _push_workflow,
)
from tests.unit.cloud_run_deploy_support import (
    run_bash as _run_bash,
)
from tests.unit.cloud_run_deploy_support import (
    run_script as _run_script,
)
from tests.unit.cloud_run_deploy_support import (
    script_env as _script_env,
)

if TYPE_CHECKING:
    from pathlib import Path

SYNCED_SHARED_CLOUD_RUN_SECRETS = {
    "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN": (
        "policyengine-api-prod-github-microdata-token"
    ),
    "OPENAI_API_KEY": "policyengine-api-prod-openai-api-key",
    "PE_UK_PRIVATE_HF_READ_TOKEN": "pe-uk-private-hf-read-token",
}


def _fake_secret_sync_gcloud(tmp_path: Path) -> tuple[Path, Path]:
    state_path = tmp_path / "secret-sync-state.json"
    state_path.write_text(
        json.dumps(
            {
                "services": {
                    STAGING_CLOUD_RUN_SERVICE: (
                        "policyengine-api-cr-staging@policyengine-api.iam."
                        "gserviceaccount.com"
                    ),
                    PRODUCTION_CLOUD_RUN_SERVICE: (
                        "policyengine-api-cr-runtime@policyengine-api.iam."
                        "gserviceaccount.com"
                    ),
                },
                "secrets": {
                    "policyengine-api-staging-db-password": "db-value",
                    "policyengine-api-prod-db-password": "db-value",
                    "policyengine-api-prod-openai-api-key": "old-openai-value",
                    "pe-uk-private-hf-read-token": "hf-value",
                },
                "iam": {},
                "version_adds": [],
            }
        ),
        encoding="utf-8",
    )
    gcloud_path = tmp_path / "gcloud-secret-sync"
    gcloud_path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_SECRET_SYNC_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]

if args[:3] == ["run", "services", "describe"]:
    print(state["services"][args[3]])
elif args[:2] == ["secrets", "describe"]:
    raise SystemExit(0 if args[2] in state["secrets"] else 1)
elif args[:2] == ["secrets", "create"]:
    state["secrets"][args[2]] = ""
elif args[:3] == ["secrets", "versions", "access"]:
    secret_name = args[args.index("--secret") + 1]
    if secret_name not in state["secrets"]:
        raise SystemExit(1)
    print(state["secrets"][secret_name], end="")
elif args[:3] == ["secrets", "versions", "add"]:
    secret_name = args[3]
    state["secrets"][secret_name] = sys.stdin.read()
    state["version_adds"].append(secret_name)
elif args[:2] == ["secrets", "add-iam-policy-binding"]:
    secret_name = args[2]
    member = args[args.index("--member") + 1]
    members = state["iam"].setdefault(secret_name, [])
    if member not in members:
        members.append(member)
elif args[:2] == ["secrets", "get-iam-policy"]:
    secret_name = args[2]
    print(
        json.dumps(
            {
                "bindings": [
                    {
                        "role": "roles/secretmanager.secretAccessor",
                        "members": state["iam"].get(secret_name, []),
                    }
                ]
            }
        )
    )
else:
    raise SystemExit(f"unexpected gcloud arguments: {args}")

state_path.write_text(json.dumps(state), encoding="utf-8")
""",
        encoding="utf-8",
    )
    gcloud_path.chmod(0o755)
    return gcloud_path, state_path


def _sync_secrets_workflow() -> str:
    return (REPO / ".github/workflows/sync-cloud-run-secrets.yml").read_text(
        encoding="utf-8"
    )


def _sync_secrets_script() -> str:
    return (REPO / ".github/scripts/sync_cloud_run_secrets.sh").read_text(
        encoding="utf-8"
    )


def test_sync_cloud_run_secrets_workflow_is_manual_and_environment_gated():
    workflow = _sync_secrets_workflow()

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "deployment_environment:" in workflow
    assert "- staging" in workflow
    assert "- production" in workflow
    assert "environment: ${{ inputs.deployment_environment }}" in workflow
    assert "id-token: write" in workflow
    checkout_step = "uses: actions/checkout@v4"
    master_gate = "bash .github/scripts/require_git_ref.sh refs/heads/master"
    gcp_authentication_step = "google-github-actions/auth@v2"
    assert checkout_step in workflow
    assert master_gate in workflow
    assert gcp_authentication_step in workflow
    # The gate runs a script from the repository, so it needs the checkout
    # first, and it must pass before anything authenticates to GCP.
    assert workflow.index(checkout_step) < workflow.index(master_gate)
    assert workflow.index(master_gate) < workflow.index(gcp_authentication_step)
    assert (
        'workload_identity_provider: "${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}"'
        in workflow
    )
    assert 'service_account: "${{ secrets.GCP_DEPLOY_SERVICE_ACCOUNT }}"' in workflow


def test_sync_cloud_run_secrets_workflow_writes_expected_secret_versions():
    workflow = _sync_secrets_workflow()
    script = _sync_secrets_script()

    assert "run: bash .github/scripts/sync_cloud_run_secrets.sh" in workflow
    assert "set +x" in script
    assert "--data-file=-" in script
    assert "Secret Manager already matches" in script
    assert "secrets versions access latest" in script
    assert "secrets add-iam-policy-binding" in script
    assert "secrets get-iam-policy" in script
    assert "run services describe" in script
    assert "roles/secretmanager.secretAccessor" in script
    assert (
        "CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET: "
        "${{ vars.CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET }}" in workflow
    )
    assert 'sync_secret POLICYENGINE_DB_PASSWORD "${db_password_secret_name}"' in script
    for env_name, secret_name in SYNCED_SHARED_CLOUD_RUN_SECRETS.items():
        assert f"{env_name}: ${{{{ secrets.{env_name} }}}}" in workflow
        assert f"sync_secret {env_name} {secret_name}" in script
    assert "verify_secret_value" in script
    assert "grant_secret_access" in script


def test_sync_cloud_run_secrets_is_idempotent_and_grants_complete_batch(tmp_path):
    gcloud_path, state_path = _fake_secret_sync_gcloud(tmp_path)
    secret_values = {
        "POLICYENGINE_DB_PASSWORD": "db-value",
        "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN": "microdata-value",
        "OPENAI_API_KEY": "openai-value",
        "PE_UK_PRIVATE_HF_READ_TOKEN": "hf-value",
    }
    env = _script_env(
        GCLOUD_BIN=str(gcloud_path),
        FAKE_SECRET_SYNC_STATE=str(state_path),
        CLOUD_RUN_PROJECT="policyengine-api",
        CLOUD_RUN_REGION="us-central1",
        CLOUD_RUN_SERVICE=PRODUCTION_CLOUD_RUN_SERVICE,
        CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET=PRODUCTION_DB_PASSWORD_SECRET,
        **secret_values,
    )

    first_result = _run_script(
        ".github/scripts/sync_cloud_run_secrets.sh",
        env,
        "--include-database-password",
    )
    assert first_result.returncode == 0, first_result.stderr
    first_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert first_state["version_adds"] == [
        "policyengine-api-prod-github-microdata-token",
        "policyengine-api-prod-openai-api-key",
    ]
    assert first_state["secrets"] == {
        "policyengine-api-staging-db-password": "db-value",
        "policyengine-api-prod-db-password": "db-value",
        "policyengine-api-prod-github-microdata-token": "microdata-value",
        "policyengine-api-prod-openai-api-key": "openai-value",
        "pe-uk-private-hf-read-token": "hf-value",
    }
    expected_member = (
        "serviceAccount:policyengine-api-cr-runtime@policyengine-api.iam."
        "gserviceaccount.com"
    )
    synchronized_secret_names = {
        "policyengine-api-prod-db-password",
        "policyengine-api-prod-github-microdata-token",
        "policyengine-api-prod-openai-api-key",
        "pe-uk-private-hf-read-token",
    }
    assert set(first_state["iam"]) == synchronized_secret_names
    assert all(members == [expected_member] for members in first_state["iam"].values())
    assert all(value not in first_result.stdout for value in secret_values.values())

    second_result = _run_script(
        ".github/scripts/sync_cloud_run_secrets.sh",
        env,
        "--include-database-password",
    )
    assert second_result.returncode == 0, second_result.stderr
    second_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert second_state["version_adds"] == first_state["version_adds"]


def test_sync_cloud_run_staging_batch_preserves_distinct_database_secret(tmp_path):
    gcloud_path, state_path = _fake_secret_sync_gcloud(tmp_path)
    env = _script_env(
        GCLOUD_BIN=str(gcloud_path),
        FAKE_SECRET_SYNC_STATE=str(state_path),
        CLOUD_RUN_PROJECT="policyengine-api",
        CLOUD_RUN_REGION="us-central1",
        CLOUD_RUN_SERVICE=STAGING_CLOUD_RUN_SERVICE,
        POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN="microdata-value",
        OPENAI_API_KEY="openai-value",
        PE_UK_PRIVATE_HF_READ_TOKEN="hf-value",
    )

    result = _run_script(
        ".github/scripts/sync_cloud_run_secrets.sh",
        env,
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["secrets"]["policyengine-api-staging-db-password"] == "db-value"
    assert "policyengine-api-staging-db-password" not in state["iam"]
    assert set(state["iam"]) == {
        "policyengine-api-prod-github-microdata-token",
        "policyengine-api-prod-openai-api-key",
        "pe-uk-private-hf-read-token",
    }


def test_hugging_face_credential_uses_purpose_specific_managed_names():
    workflow_sources = "\n".join(
        (
            _pr_workflow(),
            _push_workflow(),
            _sync_secrets_workflow(),
            _sync_secrets_script(),
            (REPO / ".github/scripts/cloud_run_env.sh").read_text(encoding="utf-8"),
        )
    )

    assert "secrets.HUGGING_FACE_TOKEN" not in workflow_sources
    assert "secrets.PE_UK_PRIVATE_HF_READ_TOKEN" in workflow_sources
    assert "policyengine-api-prod-hugging-face-token" not in workflow_sources
    assert "pe-uk-private-hf-read-token" in workflow_sources


def test_sync_cloud_run_secrets_script_is_shell_syntax_valid():
    result = _run_bash("-n", ".github/scripts/sync_cloud_run_secrets.sh")

    assert result.returncode == 0, result.stderr
