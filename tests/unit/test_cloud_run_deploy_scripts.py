from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PRODUCTION_CLOUD_SQL_INSTANCE = "policyengine-api:us-central1:policyengine-api-data"
PRODUCTION_CLOUD_RUN_SERVICE = "policyengine-api"
STAGING_CLOUD_RUN_SERVICE = "policyengine-api-staging"
TEST_V2_PROJECT_REF = "abcdefghijklmnopqrst"
TEST_V2_ENVIRONMENT = "test-foundation"
TEST_V2_RUNTIME_SECRET_RESOURCE = (
    "projects/test-project/secrets/v2-runtime-database-url/versions/latest"
)
CLOUD_RUN_SERVICE_SCRIPTS = (
    "scripts/deploy_cloud_run_candidate.sh",
    "scripts/capture_cloud_run_service_state.sh",
    "scripts/resolve_cloud_run_candidate_state.sh",
    "scripts/set_cloud_run_revision.sh",
)
DEDICATED_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT = (
    "policyengine-api-cr-runtime@policyengine-api.iam.gserviceaccount.com"
)
CLOUD_RUN_SECRET_MAPPINGS = {
    "POLICYENGINE_DB_PASSWORD": "policyengine-api-prod-db-password:latest",
    "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN": (
        "policyengine-api-prod-github-microdata-token:latest"
    ),
    "OPENAI_API_KEY": "policyengine-api-prod-openai-api-key:latest",
    "HUGGING_FACE_TOKEN": "policyengine-api-prod-hugging-face-token:latest",
}
RAW_CLOUD_RUN_SECRET_VALUES = (
    "raw-db-secret-value",
    "raw-github-secret-value",
    "raw-openai-secret-value",
    "raw-hf-secret-value",
)


def _script_env(**overrides: str) -> dict[str, str]:
    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ["PATH"],
        "CLOUD_RUN_DRY_RUN": "1",
    }
    env.update(overrides)
    return env


def _gateway_auth_env() -> dict[str, str]:
    return {
        "GATEWAY_AUTH_ISSUER": "https://issuer.example.test",
        "GATEWAY_AUTH_AUDIENCE": "simulation-gateway",
        "GATEWAY_AUTH_CLIENT_ID": "client-id",
        "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE": (
            "projects/policyengine-api/secrets/gateway-client-secret/versions/latest"
        ),
    }


def _v2_target_env() -> dict[str, str]:
    return {
        "V2_SUPABASE_PROJECT_REF": TEST_V2_PROJECT_REF,
        "V2_SUPABASE_ENVIRONMENT": TEST_V2_ENVIRONMENT,
        "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE": (TEST_V2_RUNTIME_SECRET_RESOURCE),
    }


def _required_runtime_env() -> dict[str, str]:
    return {
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": PRODUCTION_CLOUD_SQL_INSTANCE,
        "POLICYENGINE_DB_PASSWORD": "raw-db-secret-value",
        "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN": ("raw-github-secret-value"),
        "OPENAI_API_KEY": "raw-openai-secret-value",
        "HUGGING_FACE_TOKEN": "raw-hf-secret-value",
        "SIMULATION_ENTRYPOINT_URL": "https://simulation.example.test",
        "OLD_SIMULATION_GATEWAY_URL": "https://old-gateway.example.test",
        "SIM_ENTRYPOINT": "cloud_run_simulation_entrypoint",
        "ROUTE_IMPL_HEALTH": "fastapi_native",
        "ROUTE_IMPL_SPECIFICATION": "fastapi_native",
        "ROUTE_IMPL_METADATA": "fastapi_native",
        **_v2_target_env(),
        **_gateway_auth_env(),
    }


def _run_script(path: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", path],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _fake_gcloud(tmp_path: Path) -> tuple[Path, Path]:
    state_path = tmp_path / "cloud-run-state.json"
    state_path.write_text(
        json.dumps(
            {
                "service": PRODUCTION_CLOUD_RUN_SERVICE,
                "stable_url": "https://policyengine-api.example.test",
                "active_revision": "policyengine-api-00001-old",
                "candidate_revision": "policyengine-api-00002-new",
                "candidate_tag": "stage3-test",
                "candidate_url": "https://stage3-test.example.test",
                "candidate_env": {
                    "ROUTE_IMPL_HEALTH": "fastapi_native",
                    "ROUTE_IMPL_SPECIFICATION": "fastapi_native",
                    "ROUTE_IMPL_METADATA": "fastapi_native",
                },
                "updates": [],
            }
        ),
        encoding="utf-8",
    )
    gcloud_path = tmp_path / "gcloud"
    gcloud_path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_GCLOUD_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]

if args[:3] == ["run", "services", "describe"]:
    traffic = [{"revisionName": state["active_revision"], "percent": 100}]
    if state["candidate_revision"] != state["active_revision"]:
        traffic.append(
            {
                "revisionName": state["candidate_revision"],
                "tag": state["candidate_tag"],
                "url": state["candidate_url"],
            }
        )
    print(json.dumps({"status": {"url": state["stable_url"], "traffic": traffic}}))
elif args[:3] == ["run", "revisions", "describe"]:
    revision = args[3]
    revision_service = state.get("revision_services", {}).get(
        revision, state["service"]
    )
    ready = revision not in state.get("not_ready_revisions", [])
    print(
        json.dumps(
            {
                "metadata": {
                    "labels": {"serving.knative.dev/service": revision_service}
                },
                "spec": {
                    "containers": [
                        {
                            "image": (
                                "us-central1-docker.pkg.dev/project/repo/api"
                                "@sha256:candidate"
                            ),
                            "env": [
                                {"name": name, "value": value}
                                for name, value in state.get(
                                    "candidate_env", {}
                                ).items()
                            ],
                        }
                    ]
                },
                "status": {
                    "conditions": [
                        {
                            "type": "Ready",
                            "status": "True" if ready else "False",
                        }
                    ],
                    "imageDigest": (
                        "us-central1-docker.pkg.dev/project/repo/api"
                        "@sha256:candidate"
                    ),
                },
            }
        )
    )
elif args[:3] == ["run", "services", "update-traffic"]:
    target = args[args.index("--to-revisions") + 1]
    revision, percent = target.rsplit("=", 1)
    if percent != "100":
        raise SystemExit("fake gcloud only accepts 100 percent")
    state["active_revision"] = revision
    state["updates"].append(target)
    state_path.write_text(json.dumps(state), encoding="utf-8")
else:
    raise SystemExit(f"unexpected gcloud arguments: {args}")
""",
        encoding="utf-8",
    )
    gcloud_path.chmod(0o755)
    return gcloud_path, state_path


def _fake_gcloud_env(gcloud_path: Path, state_path: Path) -> dict[str, str]:
    return _script_env(
        CLOUD_RUN_DRY_RUN="0",
        CLOUD_RUN_SERVICE=PRODUCTION_CLOUD_RUN_SERVICE,
        CLOUD_RUN_TAG="stage3-test",
        GCLOUD_BIN=str(gcloud_path),
        FAKE_GCLOUD_STATE=str(state_path),
    )


def _run_simulation_version_guard(
    versions_response: dict,
    *args: str,
    entrypoint: str = "old_gateway_direct",
) -> subprocess.CompletedProcess[str]:
    versions_json = json.dumps(versions_response)
    command = (
        "curl() { printf '%s' "
        f"{shlex.quote(versions_json)}"
        '; }; . .github/request-simulation-model-versions.sh "$@"'
    )
    return subprocess.run(
        ["bash", "-c", command, "request-simulation-model-versions.sh", *args],
        cwd=REPO,
        env=_script_env(
            SIM_ENTRYPOINT=entrypoint,
            SIMULATION_ENTRYPOINT_URL="https://simulation.example.test",
            OLD_SIMULATION_GATEWAY_URL="https://old-gateway.example.test",
        ),
        text=True,
        capture_output=True,
        check=False,
    )


def _push_workflow() -> str:
    return (REPO / ".github/workflows/push.yml").read_text(encoding="utf-8")


def _pr_workflow() -> str:
    return (REPO / ".github/workflows/pr.yml").read_text(encoding="utf-8")


def _sync_secrets_workflow() -> str:
    return (REPO / ".github/workflows/sync-cloud-run-secrets.yml").read_text(
        encoding="utf-8"
    )


def _sync_secrets_script() -> str:
    return (REPO / ".github/scripts/sync_cloud_run_secrets.sh").read_text(
        encoding="utf-8"
    )


def _workflow_job_block(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"Missing workflow job {job_name}"
    return match.group("body")


def _multiline_run_block_lengths(workflow_path: Path) -> list[tuple[int, int]]:
    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[int, int]] = []

    for line_index, line in enumerate(lines):
        match = re.match(r"^(\s*)run: \|", line)
        if match is None:
            continue

        indent = len(match.group(1))
        body_lines = 0
        for body_line in lines[line_index + 1 :]:
            if body_line.strip() and len(body_line) - len(body_line.lstrip()) <= indent:
                break
            if body_line.strip():
                body_lines += 1
        blocks.append((line_index + 1, body_lines))

    return blocks


def test_cloud_run_startup_uses_asgi_entrypoint():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")

    assert "policyengine_api.asgi:app" in start_script
    assert "policyengine_api.api" not in start_script


def test_cloud_run_startup_script_is_shell_syntax_valid():
    result = subprocess.run(
        ["bash", "-n", "gcp/cloud_run/start.sh"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_simulation_version_guard_accepts_bundle_and_compatible_country_routes():
    result = _run_simulation_version_guard(
        {
            "policyengine": {
                "latest": "4.18.3",
                "4.18.3": "policyengine-simulation-py4-18-3",
            },
            "us": {
                "latest": "1.729.0",
                "1.729.0": "policyengine-simulation-py4-18-3",
            },
            "uk": {
                "latest": "2.89.2",
                "2.89.2": "policyengine-simulation-py4-18-3",
            },
        },
        "-py",
        "4.18.3",
        "-us",
        "1.729.0",
        "-uk",
        "2.89.2",
    )

    assert result.returncode == 0, result.stderr
    assert "SUCCESS: PolicyEngine bundle route is deployed and ready" in result.stdout


def test_simulation_version_guard_accepts_policyengine_bundle_route_only():
    result = _run_simulation_version_guard(
        {
            "policyengine": {
                "latest": "4.18.5",
                "4.18.5": "policyengine-simulation-py4-18-5",
            },
            "us": {},
            "uk": {},
        },
        "-py",
        "4.18.5",
    )

    assert result.returncode == 0, result.stderr
    assert "PolicyEngine .py bundle 4.18.5 is deployed" in result.stdout
    assert "SUCCESS: PolicyEngine bundle route is deployed and ready" in result.stdout


@pytest.mark.parametrize(
    ("entrypoint", "expected_url"),
    [
        ("old_gateway_direct", "https://old-gateway.example.test"),
        (
            "cloud_run_simulation_entrypoint",
            "https://simulation.example.test",
        ),
    ],
)
def test_simulation_version_guard_uses_selected_endpoint(entrypoint, expected_url):
    result = _run_simulation_version_guard(
        {
            "policyengine": {
                "4.18.5": "policyengine-simulation-py4-18-5",
            },
        },
        "-py",
        "4.18.5",
        entrypoint=entrypoint,
    )

    assert result.returncode == 0, result.stderr
    assert f"Gateway: {expected_url}" in result.stdout


@pytest.mark.parametrize(
    ("entrypoint", "missing_url"),
    [
        ("old_gateway_direct", "OLD_SIMULATION_GATEWAY_URL"),
        ("cloud_run_simulation_entrypoint", "SIMULATION_ENTRYPOINT_URL"),
    ],
)
def test_simulation_version_guard_rejects_missing_selected_endpoint(
    entrypoint,
    missing_url,
):
    command = (
        "curl() { printf '{}'; }; . .github/request-simulation-model-versions.sh \"$@\""
    )
    result = subprocess.run(
        ["bash", "-c", command, "request-simulation-model-versions.sh", "-py", "1.0"],
        cwd=REPO,
        env=_script_env(SIM_ENTRYPOINT=entrypoint),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert (
        f"{missing_url} is required when SIM_ENTRYPOINT={entrypoint}" in result.stderr
    )


def test_policyengine_bundle_support_check_passes_pyproject_pin_to_guard(tmp_path):
    capture_path = tmp_path / "guard-args.txt"
    guard_script = tmp_path / "request-simulation-model-versions.sh"
    guard_script.write_text(
        'printf "%s\\n" "$@" > "$CAPTURE_PATH"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", ".github/check-policyengine-bundle-supported.sh"],
        cwd=REPO,
        env=_script_env(
            SIMULATION_VERSION_GUARD_SCRIPT=str(guard_script),
            CAPTURE_PATH=str(capture_path),
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    current_version = re.search(r"policyengine\[models\]==([0-9.]+)", pyproject).group(
        1
    )

    assert result.returncode == 0, result.stderr
    assert capture_path.read_text(encoding="utf-8").splitlines() == [
        "-py",
        current_version,
    ]


def test_simulation_version_guard_rejects_country_route_to_different_app():
    result = _run_simulation_version_guard(
        {
            "policyengine": {
                "latest": "4.18.3",
                "4.18.3": "policyengine-simulation-py4-18-3",
            },
            "us": {
                "latest": "1.729.0",
                "1.729.0": "policyengine-simulation-us1-729-0",
            },
        },
        "-py",
        "4.18.3",
        "-us",
        "1.729.0",
    )

    assert result.returncode == 1
    assert "resolves to policyengine-simulation-us1-729-0" in result.stdout
    assert "not bundle app policyengine-simulation-py4-18-3" in result.stdout


def test_cloud_run_dockerfile_runs_startup_with_bash():
    dockerfile = (REPO / "gcp/cloud_run/Dockerfile").read_text(encoding="utf-8")

    assert 'CMD ["/bin/bash", "/app/start.sh"]' in dockerfile
    assert 'CMD ["/bin/sh", "/app/start.sh"]' not in dockerfile


def test_deployed_startup_execs_only_the_api_server():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")

    assert "exec gunicorn" in start_script
    assert "redis-server" not in start_script
    assert "redis-cli" not in start_script
    assert "CACHE_REDIS_HOST" not in start_script
    assert "CACHE_REDIS_PORT" not in start_script
    assert "CACHE_REDIS_DB" not in start_script
    assert "wait" not in start_script
    assert "pkill" not in start_script


def test_production_images_do_not_install_or_configure_embedded_redis():
    dockerfile = (REPO / "gcp/cloud_run/Dockerfile").read_text(encoding="utf-8")

    assert "redis-server" not in dockerfile
    assert "CACHE_REDIS_HOST" not in dockerfile
    assert "CACHE_REDIS_PORT" not in dockerfile
    assert "CACHE_REDIS_DB" not in dockerfile


def test_production_gunicorn_workers_do_not_inherit_database_pools():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")
    commands = "\n".join(
        line for line in start_script.splitlines() if not line.lstrip().startswith("#")
    )
    assert "--preload" not in commands


def test_validate_cloud_run_deploy_env_requires_selector_environment_variable():
    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        _script_env(
            OLD_SIMULATION_GATEWAY_URL="https://old-gateway.example.test",
            **_gateway_auth_env(),
        ),
    )

    assert result.returncode == 1
    assert "SIM_ENTRYPOINT" in result.stderr


def test_validate_cloud_run_deploy_env_accepts_direct_mode_from_environment():
    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        _script_env(
            SIM_ENTRYPOINT="old_gateway_direct",
            OLD_SIMULATION_GATEWAY_URL="https://old-gateway.example.test",
            ROUTE_IMPL_HEALTH="fastapi_native",
            ROUTE_IMPL_SPECIFICATION="fastapi_native",
            ROUTE_IMPL_METADATA="fastapi_native",
            POLICYENGINE_DB_INSTANCE_CONNECTION_NAME=PRODUCTION_CLOUD_SQL_INSTANCE,
            **_v2_target_env(),
            **_gateway_auth_env(),
        ),
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "missing_selector",
    [
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_SPECIFICATION",
        "ROUTE_IMPL_METADATA",
    ],
)
def test_validate_cloud_run_deploy_env_requires_stage6_selectors(missing_selector):
    env = _script_env(**_required_runtime_env())
    env.pop(missing_selector)

    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert result.returncode == 1
    assert missing_selector in result.stderr


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_SPECIFICATION",
        "ROUTE_IMPL_METADATA",
    ],
)
def test_validate_cloud_run_deploy_env_rejects_invalid_stage6_selectors(
    invalid_selector,
):
    env = _script_env(**_required_runtime_env())
    env[invalid_selector] = "sometimes_native"

    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert result.returncode == 1
    assert (
        f"{invalid_selector}=sometimes_native is invalid; expected "
        "flask_fallback or fastapi_native"
    ) in result.stderr


@pytest.mark.parametrize(
    ("entrypoint", "selected_url_env", "selected_url"),
    [
        (
            "old_gateway_direct",
            "OLD_SIMULATION_GATEWAY_URL",
            "https://old-gateway.example.test",
        ),
        (
            "cloud_run_simulation_entrypoint",
            "SIMULATION_ENTRYPOINT_URL",
            "https://simulation.example.test",
        ),
    ],
)
def test_validate_cloud_run_deploy_env_requires_only_selected_url(
    entrypoint,
    selected_url_env,
    selected_url,
):
    env = _script_env(
        SIM_ENTRYPOINT=entrypoint,
        ROUTE_IMPL_HEALTH="fastapi_native",
        ROUTE_IMPL_SPECIFICATION="fastapi_native",
        ROUTE_IMPL_METADATA="fastapi_native",
        POLICYENGINE_DB_INSTANCE_CONNECTION_NAME=PRODUCTION_CLOUD_SQL_INSTANCE,
        **_v2_target_env(),
        **_gateway_auth_env(),
    )
    missing_result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )
    valid_result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        {**env, selected_url_env: selected_url},
    )

    assert missing_result.returncode == 1
    assert selected_url_env in missing_result.stderr
    assert valid_result.returncode == 0, valid_result.stderr


@pytest.mark.parametrize(
    "missing_name",
    [
        "V2_SUPABASE_PROJECT_REF",
        "V2_SUPABASE_ENVIRONMENT",
    ],
)
def test_deployment_validation_requires_supabase_target_variables(
    missing_name,
):
    env = _script_env(**_required_runtime_env())
    env.pop(missing_name)

    result = _run_script(".github/scripts/validate_cloud_run_deploy_env.sh", env)

    assert result.returncode == 1
    assert missing_name in result.stderr


def test_cloud_run_requires_v2_runtime_database_configuration():
    env = _script_env(**_required_runtime_env())
    env.pop("V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE")

    cloud_run = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert cloud_run.returncode == 1
    assert "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE" in cloud_run.stderr


def test_deployment_jobs_read_supabase_identity_from_github_environment_variables():
    workflow = _push_workflow()

    for job_name in (
        "deploy-cloud-run-staging",
        "deploy-cloud-run-candidate",
    ):
        job = _workflow_job_block(workflow, job_name)
        assert "V2_SUPABASE_PROJECT_REF: ${{ vars.V2_SUPABASE_PROJECT_REF }}" in job
        assert "V2_SUPABASE_ENVIRONMENT: ${{ vars.V2_SUPABASE_ENVIRONMENT }}" in job

    for job_name in ("deploy-cloud-run-staging", "deploy-cloud-run-candidate"):
        job = _workflow_job_block(workflow, job_name)
        assert (
            "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE: "
            "${{ secrets.V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE }}" in job
        )

    assert TEST_V2_PROJECT_REF not in workflow
    assert TEST_V2_ENVIRONMENT not in workflow


def test_deployment_validation_requires_database_instance_connection_name():
    env = _script_env(**_required_runtime_env())
    env.pop("POLICYENGINE_DB_INSTANCE_CONNECTION_NAME")

    result = _run_script(".github/scripts/validate_cloud_run_deploy_env.sh", env)

    assert result.returncode == 1
    assert "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME" in result.stderr


def test_build_cloud_run_image_dry_run_uses_cloud_run_dockerfile():
    dockerignore = REPO / "gcp/cloud_run/Dockerfile.dockerignore"

    assert dockerignore.exists()
    assert "policyengine_api/data/*.db" in dockerignore.read_text(encoding="utf-8")

    result = _run_script(
        ".github/scripts/build_cloud_run_image.sh",
        _script_env(
            GITHUB_SHA="1234567890abcdef",
            GITHUB_RUN_NUMBER="42",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "gcp/cloud_run/Dockerfile" in result.stdout
    assert "--platform linux/amd64" in result.stdout
    assert "docker push" in result.stdout
    assert (
        "us-central1-docker.pkg.dev/policyengine-api/policyengine-api/"
        "policyengine-api:1234567890abcdef"
    ) in result.stdout


def test_deploy_cloud_run_candidate_dry_run_never_shifts_traffic():
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "gcloud run deploy" in result.stdout
    assert "--no-traffic" in result.stdout
    assert "stage3-test" in result.stdout
    assert (
        f"--service-account {DEDICATED_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT}"
        in result.stdout
    )
    assert f"--add-cloudsql-instances {PRODUCTION_CLOUD_SQL_INSTANCE}" in result.stdout
    assert (
        f"POLICYENGINE_DB_INSTANCE_CONNECTION_NAME={PRODUCTION_CLOUD_SQL_INSTANCE}"
        in result.stdout
    )
    assert "--set-secrets" in result.stdout
    assert "--network default" in result.stdout
    assert "--subnet default" in result.stdout
    assert "--vpc-egress private-ranges-only" in result.stdout
    assert "RUNTIME_CACHE_MODE=deployed" in result.stdout
    assert "RUNTIME_CACHE_ENVIRONMENT=production" in result.stdout
    assert "RUNTIME_CACHE_SERVICE=api" in result.stdout
    assert (
        "RUNTIME_CACHE_URL=policyengine-api-prod-runtime-cache-url:latest"
        in result.stdout
    )
    assert (
        "RUNTIME_CACHE_CA_CERT=policyengine-api-prod-runtime-cache-ca:latest"
        in result.stdout
    )
    assert f"V2_SUPABASE_PROJECT_REF={TEST_V2_PROJECT_REF}" in result.stdout
    assert f"V2_SUPABASE_ENVIRONMENT={TEST_V2_ENVIRONMENT}" in result.stdout
    assert (
        f"V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE="
        f"{TEST_V2_RUNTIME_SECRET_RESOURCE}" in result.stdout
    )
    assert "V2_DATABASE_URL" not in result.stdout
    assert "V2_STORAGE_ADMIN_KEY" not in result.stdout
    for env_name, secret_ref in CLOUD_RUN_SECRET_MAPPINGS.items():
        assert f"{env_name}={secret_ref}" in result.stdout
    for raw_secret_value in RAW_CLOUD_RUN_SECRET_VALUES:
        assert raw_secret_value not in result.stdout
    assert "CLOUD_RUN_INTERNAL_PROBES" not in result.stdout
    assert "--to-latest" not in result.stdout
    assert "update-traffic" not in result.stdout
    assert (
        "OLD_SIMULATION_GATEWAY_URL=https://old-gateway.example.test" in result.stdout
    )
    assert "SIM_ENTRYPOINT=cloud_run_simulation_entrypoint" in result.stdout
    for selector in (
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_SPECIFICATION",
        "ROUTE_IMPL_METADATA",
    ):
        assert result.stdout.count(f"{selector}=fastapi_native") == 1


def test_staging_and_production_use_distinct_cloud_run_runtime_identities():
    workflow = _push_workflow()
    staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    assert (
        "policyengine-api-cr-staging@policyengine-api.iam.gserviceaccount.com"
        in staging
    )
    assert "GCP_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT" not in staging
    assert "GCP_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT" in production


def test_deploy_cloud_run_candidate_uses_configured_database_instance():
    configured_instance = "project:region:configured-instance"
    env = {
        **_required_runtime_env(),
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": configured_instance,
    }
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **env,
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert f"--add-cloudsql-instances {configured_instance}" in result.stdout
    assert (
        f"POLICYENGINE_DB_INSTANCE_CONNECTION_NAME={configured_instance}"
        in result.stdout
    )
    assert PRODUCTION_CLOUD_SQL_INSTANCE not in result.stdout


@pytest.mark.parametrize(
    ("entrypoint", "selected_url_env", "selected_url", "unselected_url_env"),
    [
        (
            "old_gateway_direct",
            "OLD_SIMULATION_GATEWAY_URL",
            "https://old-gateway.example.test",
            "SIMULATION_ENTRYPOINT_URL",
        ),
        (
            "cloud_run_simulation_entrypoint",
            "SIMULATION_ENTRYPOINT_URL",
            "https://simulation.example.test",
            "OLD_SIMULATION_GATEWAY_URL",
        ),
    ],
)
def test_deploy_cloud_run_candidate_passes_only_configured_simulation_urls(
    entrypoint,
    selected_url_env,
    selected_url,
    unselected_url_env,
):
    env = {
        **_script_env(),
        **_required_runtime_env(),
        "SIM_ENTRYPOINT": entrypoint,
        selected_url_env: selected_url,
        "CLOUD_RUN_IMAGE_URI": ("us-central1-docker.pkg.dev/project/repo/api:sha"),
        "CLOUD_RUN_TAG": "stage3-test",
    }
    env.pop(unselected_url_env)

    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        env,
    )

    assert result.returncode == 0, result.stderr
    assert f"{selected_url_env}={selected_url}" in result.stdout
    assert f"{unselected_url_env}=" not in result.stdout


def test_deploy_cloud_run_candidate_requires_selector_environment_variable():
    env = {
        **_script_env(),
        **_required_runtime_env(),
        "OLD_SIMULATION_GATEWAY_URL": "https://old-gateway.example.test",
        "CLOUD_RUN_IMAGE_URI": "us-central1-docker.pkg.dev/project/repo/api:sha",
        "CLOUD_RUN_TAG": "stage3-test",
    }
    env.pop("SIM_ENTRYPOINT")
    env.pop("SIMULATION_ENTRYPOINT_URL")

    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        env,
    )

    assert result.returncode == 1
    assert "SIM_ENTRYPOINT" in result.stderr


def test_manual_simulation_entrypoint_ramp_is_removed():
    assert not (REPO / ".github/scripts/ramp_simulation_entrypoint.sh").exists()
    assert not (REPO / ".github/workflows/ramp-simulation-entrypoint.yml").exists()


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


def test_resolve_cloud_run_candidate_verifies_stage6_route_selectors(tmp_path):
    gcloud_path, state_path = _fake_gcloud(tmp_path)
    env = {
        **_fake_gcloud_env(gcloud_path, state_path),
        "ROUTE_IMPL_HEALTH": "fastapi_native",
        "ROUTE_IMPL_SPECIFICATION": "fastapi_native",
        "ROUTE_IMPL_METADATA": "fastapi_native",
    }

    result = _run_script(
        ".github/scripts/resolve_cloud_run_candidate_state.sh",
        env,
    )

    assert result.returncode == 0, result.stderr


def test_resolve_cloud_run_candidate_rejects_stage6_selector_mismatch(tmp_path):
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
        },
    )

    assert result.returncode == 2
    assert (
        "Revision policyengine-api-00002-new has ROUTE_IMPL_METADATA="
        "flask_fallback; expected fastapi_native"
    ) in result.stderr


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


def test_deploy_cloud_run_candidate_pins_runtime_shape():
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
        ),
    )

    assert result.returncode == 0, result.stderr
    # Stage 2-qualified values, pinned on every deploy — rationale in
    # docs/migration/cloud-run-operations.md ("Runtime shape and scaling").
    assert "--concurrency 6 " in result.stdout
    assert "WEB_CONCURRENCY=2" in result.stdout
    # Revision-level floor (--min-instances) stays 0; the warm floor is applied
    # service-level (--min), defaulting to 0 unless a job overrides it.
    assert "--min-instances 0 " in result.stdout
    assert "--min 0 " in result.stdout


def test_deploy_cloud_run_candidate_applies_service_level_min_floor():
    """The warm floor is service-level (--min), never revision-level.

    A positive --min-instances is immutably baked onto every new revision, so
    each tagged no-traffic candidate would pin its own warm instances. --min
    keeps one floor across whichever revision is serving, with no per-tag cost.
    """
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
            CLOUD_RUN_SERVICE_MIN_INSTANCES="2",
        ),
    )

    assert result.returncode == 0, result.stderr
    # Service-level floor honoured, and the revision-level floor stays 0 so the
    # candidate does not pin per-tag warm instances.
    assert "--min 2 " in result.stdout
    assert "--min-instances 0 " in result.stdout


def test_deploy_cloud_run_candidate_pins_http_startup_probe():
    """The startup probe must poll readiness over HTTP, never TCP.

    gunicorn's master binds the port long before a worker finishes importing,
    so a TCP probe reports "started" while the app cannot answer and Cloud Run
    routes live traffic onto it. Probing /readiness-check makes Cloud Run
    withhold traffic until the app can actually serve.
    """
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "--startup-probe " in result.stdout
    assert "httpGet.path=/readiness-check" in result.stdout
    assert "httpGet.port=8080" in result.stdout
    # A tcpSocket probe would reintroduce routing-before-ready.
    assert "tcpSocket" not in result.stdout

    probe = next(
        part
        for part in result.stdout.split()
        if "httpGet.path=/readiness-check" in part
    )
    # The dry-run echoes the command shell-escaped, so commas arrive as "\,".
    settings = dict(
        item.split("=", 1) for item in probe.replace("\\", "").split(",") if "=" in item
    )
    period = int(settings["periodSeconds"])
    threshold = int(settings["failureThreshold"])
    initial_delay = int(settings["initialDelaySeconds"])

    # Cloud Run caps EACH half at 240s and shuts the container down past the
    # total, so both halves and their sum are load-bearing.
    assert threshold * period <= 240, "failureThreshold x periodSeconds > 240s cap"
    assert initial_delay <= 240, "initialDelaySeconds > 240s cap"
    # initialDelaySeconds is additive (no probe runs during it), so the real
    # deadline is the sum. Readiness now gates on the startup warmup too, so
    # boot-to-ready is the ~371s p90 import PLUS the warmup calculate; keep the
    # window at (or near) the 480s platform maximum — see cloud-run-operations.md.
    assert initial_delay + threshold * period >= 470
    # initialDelaySeconds also delays availability, but boot (import + warmup)
    # exceeds the p50 either way, so a high initialDelay adds no real scale-out
    # delay.
    assert int(settings["timeoutSeconds"]) <= period


def test_push_workflow_pins_cloud_run_scaling_per_job():
    workflow = _push_workflow()
    staging_deploy = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    production_deploy = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    assert 'CLOUD_RUN_MIN_INSTANCES: "0"' in staging_deploy
    assert 'CLOUD_RUN_MAX_INSTANCES: "1"' in staging_deploy
    assert 'CLOUD_RUN_MAX_INSTANCES: "8"' in production_deploy
    # Production keeps a service-level warm floor of 2; staging stays at 0.
    assert 'CLOUD_RUN_SERVICE_MIN_INSTANCES: "2"' in production_deploy
    assert 'CLOUD_RUN_SERVICE_MIN_INSTANCES: "0"' in staging_deploy
    # Revision-level min-instances must stay 0 EVERYWHERE in the workflow —
    # including workflow-level env, which flows into every job. Any mention
    # of the variable must be an explicit "0" pin.
    assert workflow.count("CLOUD_RUN_MIN_INSTANCES:") == workflow.count(
        'CLOUD_RUN_MIN_INSTANCES: "0"'
    )
    # The runtime-shape values live only in cloud_run_env.sh (where the
    # dry-run test validates them); no workflow-level or job-level override
    # may exist anywhere in this file.
    assert "CLOUD_RUN_CONCURRENCY" not in workflow
    assert "CLOUD_RUN_WEB_CONCURRENCY" not in workflow


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


def _workflow_job_names(workflow: str) -> list[str]:
    return re.findall(r"^  ([a-zA-Z0-9_-]+):$", workflow, flags=re.MULTILINE)


def test_push_workflow_isolates_staging_cloud_run_service():
    workflow = _push_workflow()
    staging_deploy = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    staging_promote = _workflow_job_block(workflow, "promote-cloud-run-staging")
    production_deploy = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    staging_service_env = f"CLOUD_RUN_SERVICE: {STAGING_CLOUD_RUN_SERVICE}"
    assert staging_service_env in staging_deploy
    assert staging_service_env in staging_promote
    assert STAGING_CLOUD_RUN_SERVICE not in production_deploy
    assert f"CLOUD_RUN_SERVICE: {PRODUCTION_CLOUD_RUN_SERVICE}\n" in production_deploy


def test_every_cloud_run_job_pins_a_service():
    workflow = _push_workflow()

    for job_name in _workflow_job_names(workflow):
        block = _workflow_job_block(workflow, job_name)
        if not any(script in block for script in CLOUD_RUN_SERVICE_SCRIPTS):
            continue
        assert re.search(r"CLOUD_RUN_SERVICE: \S+", block), (
            f"Job {job_name} uses a service-targeting Cloud Run script without "
            "pinning CLOUD_RUN_SERVICE; the cloud_run_env.sh default silently "
            "targets production"
        )


def test_only_production_job_promotes_the_production_cloud_run_service():
    workflow = _push_workflow()

    for job_name in _workflow_job_names(workflow):
        block = _workflow_job_block(workflow, job_name)
        if "scripts/set_cloud_run_revision.sh" not in block:
            continue
        if job_name == "deploy-cloud-run-candidate":
            expected = f"CLOUD_RUN_SERVICE: {PRODUCTION_CLOUD_RUN_SERVICE}\n"
        else:
            expected = f"CLOUD_RUN_SERVICE: {STAGING_CLOUD_RUN_SERVICE}"
        assert expected in block, (
            f"Job {job_name} promotes Cloud Run traffic without pinning the "
            "expected service"
        )


def test_build_cloud_run_image_uri_is_independent_of_service_override():
    result = _run_script(
        ".github/scripts/build_cloud_run_image.sh",
        _script_env(
            GITHUB_SHA="1234567890abcdef",
            GITHUB_RUN_NUMBER="42",
            CLOUD_RUN_SERVICE=STAGING_CLOUD_RUN_SERVICE,
        ),
    )

    assert result.returncode == 0, result.stderr
    assert (
        "us-central1-docker.pkg.dev/policyengine-api/policyengine-api/"
        "policyengine-api:1234567890abcdef"
    ) in result.stdout
    assert f"{STAGING_CLOUD_RUN_SERVICE}:" not in result.stdout


def test_deploy_cloud_run_candidate_dry_run_targets_service_override():
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
            CLOUD_RUN_SERVICE=STAGING_CLOUD_RUN_SERVICE,
        ),
    )

    assert result.returncode == 0, result.stderr
    assert f"gcloud run deploy {STAGING_CLOUD_RUN_SERVICE}" in result.stdout


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


def test_push_workflow_runs_release_and_cloud_run_staging_tests():
    workflow = _push_workflow()
    cloud_run_deploy = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    cloud_run_tests = _workflow_job_block(
        workflow,
        "integration-tests-staging-cloud-run",
    )
    cloud_run_promotion = _workflow_job_block(workflow, "promote-cloud-run-staging")
    production_gate = _workflow_job_block(
        workflow,
        "ensure-production-model-version-aligns-with-sim-api",
    )
    cloud_run_test_command = (
        "python -m pytest tests/integration/test_cloud_run_candidate.py "
        "tests/integration/test_live_v2_metadata.py "
        "tests/integration/test_live_calculate.py "
        "tests/integration/test_live_economy.py "
        "tests/integration/test_live_budget_window_cache.py -v"
    )

    assert "make test" in cloud_run_deploy
    assert cloud_run_deploy.index("make test") < cloud_run_deploy.index(
        'uses: "google-github-actions/auth@v2"'
    )
    assert cloud_run_deploy.index("make test") < cloud_run_deploy.index(
        "Build and push Cloud Run image"
    )
    assert cloud_run_test_command in cloud_run_tests
    assert (
        "API_BASE_URL: ${{ needs.deploy-cloud-run-staging.outputs.url }}"
        in cloud_run_tests
    )
    assert "needs: promote-cloud-run-staging" in production_gate
    assert "- integration-tests-staging-cloud-run" not in production_gate
    assert "- integration-tests-staging-cloud-run" in cloud_run_promotion
    assert "qualify-stage6-read-routes-staging" not in workflow
    assert "qualify_stage6_read_routes.sh" not in workflow
    assert "bash .github/scripts/set_cloud_run_revision.sh" in cloud_run_promotion
    assert (
        "CLOUD_RUN_TARGET_REVISION: "
        "${{ needs.deploy-cloud-run-staging.outputs.revision }}" in cloud_run_promotion
    )
    assert "Restore previous Cloud Run staging revision" in cloud_run_promotion
    assert (
        "${{ needs.deploy-cloud-run-staging.outputs.stable_url }}/readiness-check"
        in cloud_run_promotion
    )
    verify_index = cloud_run_promotion.index(
        "Verify exact tested Cloud Run staging candidate"
    )
    promote_index = cloud_run_promotion.index("Promote Cloud Run staging candidate")
    assert verify_index < promote_index
    assert (
        "CLOUD_RUN_EXPECTED_REVISION: "
        "${{ needs.deploy-cloud-run-staging.outputs.revision }}" in cloud_run_promotion
    )
    assert (
        "CLOUD_RUN_EXPECTED_IMAGE: "
        "${{ needs.deploy-cloud-run-staging.outputs.image }}" in cloud_run_promotion
    )


def test_push_workflow_uses_local_redis_for_predeployment_test_suite():
    staging = _workflow_job_block(_push_workflow(), "deploy-cloud-run-staging")
    test_step_start = staging.index("- name: Run release tests")
    test_step_end = staging.index("- name: GCP authentication", test_step_start)
    test_step = staging[test_step_start:test_step_end]

    assert "RUNTIME_CACHE_MODE: local" in test_step
    assert "RUNTIME_CACHE_URL: redis://127.0.0.1:6379/0" in test_step
    assert 'RUNTIME_CACHE_URL_SECRET_RESOURCE: ""' in test_step
    assert 'RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE: ""' in test_step
    assert "RUNTIME_CACHE_ENVIRONMENT: test" in test_step
    assert "RUNTIME_CACHE_SERVICE: api" in test_step
    assert "-u ROUTE_IMPL_HEALTH" in test_step
    assert "-u CLOUD_RUN_SERVICE" in test_step
    assert "-u V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE" in test_step


def test_push_workflow_staging_precedes_all_production_deployments():
    workflow = _push_workflow()
    docker_publish = _workflow_job_block(workflow, "docker")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    assert "needs: seed-v2-production-database" in cloud_run_production
    assert "needs: deploy-cloud-run-candidate" in docker_publish
    assert "stage3-prod-" in cloud_run_production
    assert "Build and push Cloud Run image" not in cloud_run_production


def test_push_workflow_serializes_deployments_without_cancelling_in_progress_run():
    workflow = _push_workflow()

    assert "concurrency:\n  group: deploy\n  cancel-in-progress: false" in workflow


def test_workflows_do_not_store_simulation_selector_in_git():
    workflow = _push_workflow()
    pr_workflow = _pr_workflow()

    assert not (REPO / ".github/simulation-entrypoint-mode").exists()
    for workflow_text in (workflow, pr_workflow):
        assert (
            workflow_text.count(
                "OLD_SIMULATION_GATEWAY_URL: ${{ vars.OLD_SIMULATION_GATEWAY_URL }}"
            )
            == 1
        )
        assert (
            "SIM_ENTRYPOINT: ${{ vars.SIM_ENTRYPOINT }}"
            not in workflow_text.split("jobs:", maxsplit=1)[0]
        )


def test_workflows_scope_simulation_routing_config_to_github_environments():
    selector_env = "SIM_ENTRYPOINT: ${{ vars.SIM_ENTRYPOINT }}"
    secret_env = "SIMULATION_ENTRYPOINT_URL: ${{ secrets.SIMULATION_ENTRYPOINT_URL }}"
    pr_workflow = _pr_workflow()
    push_workflow = _push_workflow()

    assert secret_env not in pr_workflow.split("jobs:", maxsplit=1)[0]
    assert secret_env not in push_workflow.split("jobs:", maxsplit=1)[0]
    assert selector_env not in pr_workflow.split("jobs:", maxsplit=1)[0]
    assert selector_env not in push_workflow.split("jobs:", maxsplit=1)[0]

    environment_jobs = (
        (
            pr_workflow,
            "ensure-policyengine-bundle-supported-by-simulation-api",
            "staging",
        ),
        (
            push_workflow,
            "ensure-staging-model-version-aligns-with-sim-api",
            "staging",
        ),
        (push_workflow, "deploy-cloud-run-staging", "staging"),
        (
            push_workflow,
            "ensure-production-model-version-aligns-with-sim-api",
            "production",
        ),
        (push_workflow, "deploy-cloud-run-candidate", "production"),
    )
    for workflow_text, job_name, environment in environment_jobs:
        job = _workflow_job_block(workflow_text, job_name)
        assert f"environment: {environment}" in job
        assert selector_env in job
        assert secret_env in job


def test_cloud_run_deploy_jobs_use_environment_scoped_stage6_route_selectors():
    workflow = _push_workflow()
    selectors = (
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_SPECIFICATION",
        "ROUTE_IMPL_METADATA",
    )

    for job_name, environment in (
        ("deploy-cloud-run-staging", "staging"),
        ("deploy-cloud-run-candidate", "production"),
    ):
        job = _workflow_job_block(workflow, job_name)
        assert f"environment: {environment}" in job
        for selector in selectors:
            assert f"{selector}: ${{{{ vars.{selector} }}}}" in job


def test_all_deploy_jobs_use_github_database_instance_variable():
    workflow = _push_workflow()
    instance_env = (
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME: "
        "${{ vars.POLICYENGINE_DB_INSTANCE_CONNECTION_NAME }}"
    )

    for job_name in (
        "deploy-cloud-run-staging",
        "deploy-cloud-run-candidate",
    ):
        assert instance_env in _workflow_job_block(workflow, job_name)


def test_deployment_consumers_require_selector_from_environment():
    consumers = (
        ".github/request-simulation-model-versions.sh",
        ".github/scripts/validate_cloud_run_deploy_env.sh",
    )

    for consumer in consumers:
        script = (REPO / consumer).read_text(encoding="utf-8")
        assert "source .github/scripts/simulation_entrypoint_env.sh" in script
        assert "simulation_entrypoint_load_git_selection" not in script


def test_workflows_never_depend_on_opaque_legacy_simulation_url_secret():
    workflows = "\n".join(
        workflow.read_text(encoding="utf-8")
        for workflow in (REPO / ".github/workflows").glob("*.y*ml")
    )

    assert "SIMULATION_API_URL" not in workflows
    assert "vars.SIMULATION_ENTRYPOINT_URL" not in workflows
    assert "secrets.SIMULATION_ENTRYPOINT_URL" in workflows
    assert "secrets.OLD_SIMULATION_GATEWAY_URL" not in workflows


def test_push_workflow_uses_dedicated_cloud_run_runtime_service_account():
    workflow = _push_workflow()
    cloud_run_staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    runtime_account_secret = (
        "CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT: "
        "${{ secrets.GCP_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT }}"
    )
    deploy_account_secret = (
        "CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT: ${{ secrets.GCP_DEPLOY_SERVICE_ACCOUNT }}"
    )

    assert (
        "CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT: "
        "policyengine-api-cr-staging@policyengine-api.iam.gserviceaccount.com"
        in cloud_run_staging
    )
    assert runtime_account_secret not in cloud_run_staging
    assert runtime_account_secret in cloud_run_production
    assert deploy_account_secret not in cloud_run_staging
    assert deploy_account_secret not in cloud_run_production


def test_push_workflow_does_not_pass_raw_secrets_to_cloud_run_deploy_commands():
    workflow = _push_workflow()
    cloud_run_staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")
    staging_deploy_start = cloud_run_staging.index(
        "- name: Deploy tagged Cloud Run staging candidate"
    )
    staging_deploy_end = cloud_run_staging.index(
        "- name: Resolve exact Cloud Run staging candidate",
        staging_deploy_start,
    )
    staging_deploy = cloud_run_staging[staging_deploy_start:staging_deploy_end]
    raw_secret_envs = (
        "POLICYENGINE_DB_PASSWORD: ${{ secrets.POLICYENGINE_DB_PASSWORD }}",
        (
            "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN: "
            "${{ secrets.POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN }}"
        ),
        "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}",
        "HUGGING_FACE_TOKEN: ${{ secrets.HUGGING_FACE_TOKEN }}",
    )

    for raw_secret_env in raw_secret_envs:
        assert raw_secret_env not in staging_deploy
        assert raw_secret_env not in cloud_run_production


def test_push_workflow_release_test_step_is_the_only_raw_secret_consumer():
    workflow = _push_workflow()
    cloud_run_staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")
    test_step_start = cloud_run_staging.index("- name: Run release tests")
    test_step_end = cloud_run_staging.index(
        "- name: GCP authentication",
        test_step_start,
    )
    release_test_step = cloud_run_staging[test_step_start:test_step_end]

    raw_secret_envs = (
        "POLICYENGINE_DB_PASSWORD: ${{ secrets.POLICYENGINE_DB_PASSWORD }}",
        (
            "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN: "
            "${{ secrets.POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN }}"
        ),
        "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}",
        "HUGGING_FACE_TOKEN: ${{ secrets.HUGGING_FACE_TOKEN }}",
    )
    for raw_secret_env in raw_secret_envs:
        assert release_test_step.count(raw_secret_env) == 1
        assert cloud_run_staging.count(raw_secret_env) == 1
        assert raw_secret_env not in cloud_run_production


def test_sync_cloud_run_secrets_workflow_is_manual_and_environment_gated():
    workflow = _sync_secrets_workflow()

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "environment: production" in workflow
    assert "id-token: write" in workflow
    assert "github.ref != 'refs/heads/master'" in workflow
    assert "google-github-actions/auth@v2" in workflow
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
    assert "gcloud secrets add-iam-policy-binding" in script
    assert "roles/secretmanager.secretAccessor" in script
    for env_name, secret_ref in CLOUD_RUN_SECRET_MAPPINGS.items():
        secret_name = secret_ref.removesuffix(":latest")
        assert f"{env_name}: ${{{{ secrets.{env_name} }}}}" in workflow
        assert f"sync_secret {env_name} {secret_name}" in script


def test_sync_cloud_run_secrets_script_is_shell_syntax_valid():
    result = subprocess.run(
        ["bash", "-n", ".github/scripts/sync_cloud_run_secrets.sh"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_changelog_fragment_script_is_shell_syntax_valid():
    result = subprocess.run(
        ["bash", "-n", ".github/scripts/check_changelog_fragment.sh"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_workflows_do_not_inline_long_run_blocks():
    oversized_blocks = []
    for workflow_path in (REPO / ".github/workflows").glob("*.y*ml"):
        for line_number, body_lines in _multiline_run_block_lengths(workflow_path):
            if body_lines > 4:
                oversized_blocks.append(
                    f"{workflow_path.relative_to(REPO)}:{line_number} has "
                    f"{body_lines} inline run lines"
                )

    assert oversized_blocks == []


def test_push_workflow_promotes_production_cloud_run_after_candidate_smoke():
    workflow = _push_workflow()
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")
    smoke_index = cloud_run_production.index(
        "python -m pytest tests/integration/test_cloud_run_candidate.py "
        "tests/integration/test_live_v2_metadata.py -v"
    )
    promote_index = cloud_run_production.index(
        "bash .github/scripts/set_cloud_run_revision.sh"
    )

    assert smoke_index < promote_index
    assert "SIM_ENTRYPOINT: ${{ vars.SIM_ENTRYPOINT }}" in cloud_run_production
    assert (
        "CLOUD_RUN_TARGET_REVISION: ${{ steps.candidate.outputs.revision }}"
        in cloud_run_production
    )
    assert (
        "CLOUD_RUN_EXPECTED_CURRENT_REVISION: "
        "${{ steps.previous.outputs.revision }}" in cloud_run_production
    )
    assert "Restore previous Cloud Run production revision" in cloud_run_production
    assert (
        "${{ steps.previous.outputs.stable_url }}/readiness-check"
        in cloud_run_production
    )
    verify_index = cloud_run_production.index(
        "Verify exact tested Cloud Run production candidate"
    )
    assert smoke_index < verify_index < promote_index
    assert (
        "CLOUD_RUN_EXPECTED_REVISION: ${{ steps.candidate.outputs.revision }}"
        in cloud_run_production
    )
    assert (
        "CLOUD_RUN_EXPECTED_IMAGE: ${{ steps.candidate.outputs.image }}"
        in cloud_run_production
    )


def test_push_workflow_never_uses_latest_or_tag_alias_for_cloud_run_traffic():
    workflow = _push_workflow()
    promotion_script = (REPO / ".github/scripts/set_cloud_run_revision.sh").read_text(
        encoding="utf-8"
    )

    assert "--to-tags" not in workflow
    assert "--to-latest" not in workflow.lower()
    assert "--to-revisions" in promotion_script
    assert '"${target_revision}=100"' in promotion_script
