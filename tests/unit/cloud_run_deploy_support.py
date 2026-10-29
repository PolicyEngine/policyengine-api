"""Helpers and constants shared by the Cloud Run deployment script tests."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


PRODUCTION_CLOUD_SQL_INSTANCE = "policyengine-api:us-central1:policyengine-api-data"


PRODUCTION_CLOUD_RUN_SERVICE = "policyengine-api"


STAGING_CLOUD_RUN_SERVICE = "policyengine-api-staging"


TEST_V2_PROJECT_REF = "abcdefghijklmnopqrst"


TEST_V2_ENVIRONMENT = "test-foundation"


TEST_V2_RUNTIME_SECRET_RESOURCE = (
    "projects/test-project/secrets/v2-runtime-database-url/versions/latest"
)


TEST_AUTH0_SECRET_RESOURCE = "projects/p/secrets/auth0-management/versions/latest"


TEST_OTEL_ENDPOINT = "https://collector.example.test"


PRODUCTION_DB_PASSWORD_SECRET = "policyengine-api-prod-db-password:latest"


def script_env(**overrides: str) -> dict[str, str]:
    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ["PATH"],
        "CLOUD_RUN_DRY_RUN": "1",
    }
    env.update(overrides)
    return env


def gateway_auth_env() -> dict[str, str]:
    return {
        "GATEWAY_AUTH_ISSUER": "https://issuer.example.test",
        "GATEWAY_AUTH_AUDIENCE": "simulation-gateway",
        "GATEWAY_AUTH_CLIENT_ID": "client-id",
        "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE": (
            "projects/policyengine-api/secrets/gateway-client-secret/versions/latest"
        ),
    }


def public_api_auth_env() -> dict[str, str]:
    return {
        "PUBLIC_API_AUTH_REQUIRED": "1",
        "PUBLIC_API_AUTH_ISSUER": "https://auth.example.test/",
        "PUBLIC_API_AUTH_AUDIENCE": "https://api.policyengine.org/",
    }


def v2_target_env() -> dict[str, str]:
    return {
        "V2_SUPABASE_PROJECT_REF": TEST_V2_PROJECT_REF,
        "V2_SUPABASE_ENVIRONMENT": TEST_V2_ENVIRONMENT,
        "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE": (TEST_V2_RUNTIME_SECRET_RESOURCE),
    }


def observability_env() -> dict[str, str]:
    return {
        "OBSERVABILITY_SERVICE_NAMESPACE": "policyengine.api-v1",
        "OBSERVABILITY_TRACE_PROJECT_ID": "central-observability",
        "OTEL_EXPORTER_OTLP_ENDPOINT": TEST_OTEL_ENDPOINT,
        "POLICYENGINE_OTEL_GOOGLE_AUDIENCE": TEST_OTEL_ENDPOINT,
    }


def required_runtime_env() -> dict[str, str]:
    return {
        "DEPLOYMENT_ENVIRONMENT": "production",
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": PRODUCTION_CLOUD_SQL_INSTANCE,
        "PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
            PRODUCTION_CLOUD_SQL_INSTANCE
        ),
        "PRODUCTION_V2_SUPABASE_PROJECT_REF": TEST_V2_PROJECT_REF,
        "PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE": (
            TEST_V2_RUNTIME_SECRET_RESOURCE
        ),
        "PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET": (
            PRODUCTION_DB_PASSWORD_SECRET
        ),
        "CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET": PRODUCTION_DB_PASSWORD_SECRET,
        "POLICYENGINE_DB_PASSWORD": "raw-db-secret-value",
        "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN": ("raw-github-secret-value"),
        "OPENAI_API_KEY": "raw-openai-secret-value",
        "PE_UK_PRIVATE_HF_READ_TOKEN": "raw-hf-secret-value",
        "SIMULATION_ENTRYPOINT_URL": "https://simulation.example.test",
        "OLD_SIMULATION_GATEWAY_URL": "https://old-gateway.example.test",
        "SIM_ENTRYPOINT": "cloud_run_simulation_entrypoint",
        "ROUTE_IMPL_HEALTH": "fastapi_native",
        "ROUTE_IMPL_SPECIFICATION": "fastapi_native",
        "ROUTE_IMPL_METADATA": "fastapi_native",
        "ROUTE_IMPL_POLICY": "flask_fallback",
        "ROUTE_IMPL_HOUSEHOLD": "flask_fallback",
        "DB_READ_POLICY": "cloud_sql",
        "DB_WRITE_POLICY": "cloud_sql",
        "DB_READ_HOUSEHOLD": "cloud_sql",
        "DB_WRITE_HOUSEHOLD": "cloud_sql",
        **observability_env(),
        **v2_target_env(),
        **gateway_auth_env(),
        **public_api_auth_env(),
    }


def run_bash(
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", *arguments],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def run_script(
    path: str,
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return run_bash(path, *args, env=env)


def fake_gcloud(tmp_path: Path) -> tuple[Path, Path]:
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
                    "ROUTE_IMPL_POLICY": "flask_fallback",
                    "ROUTE_IMPL_HOUSEHOLD": "flask_fallback",
                    "DB_READ_POLICY": "cloud_sql",
                    "DB_WRITE_POLICY": "cloud_sql",
                    "DB_READ_HOUSEHOLD": "cloud_sql",
                    "DB_WRITE_HOUSEHOLD": "cloud_sql",
                    "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
                        PRODUCTION_CLOUD_SQL_INSTANCE
                    ),
                    "V2_SUPABASE_PROJECT_REF": TEST_V2_PROJECT_REF,
                    "V2_SUPABASE_ENVIRONMENT": TEST_V2_ENVIRONMENT,
                    "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE": (
                        TEST_V2_RUNTIME_SECRET_RESOURCE
                    ),
                },
                "candidate_cloud_sql": PRODUCTION_CLOUD_SQL_INSTANCE,
                "candidate_secret_env": {
                    "HUGGING_FACE_TOKEN": {
                        "name": "pe-uk-private-hf-read-token",
                        "key": "latest",
                    }
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
                    "labels": {"serving.knative.dev/service": revision_service},
                    "annotations": {
                        "run.googleapis.com/cloudsql-instances": state.get(
                            "candidate_cloud_sql", ""
                        )
                    },
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
                            ]
                            + [
                                {
                                    "name": name,
                                    "valueFrom": {"secretKeyRef": reference},
                                }
                                for name, reference in state.get(
                                    "candidate_secret_env", {}
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


def fake_gcloud_env(gcloud_path: Path, state_path: Path) -> dict[str, str]:
    return script_env(
        CLOUD_RUN_DRY_RUN="0",
        CLOUD_RUN_SERVICE=PRODUCTION_CLOUD_RUN_SERVICE,
        CLOUD_RUN_TAG="stage3-test",
        GCLOUD_BIN=str(gcloud_path),
        FAKE_GCLOUD_STATE=str(state_path),
    )


def push_workflow() -> str:
    return (REPO / ".github/workflows/push.yml").read_text(encoding="utf-8")


def pr_workflow() -> str:
    return (REPO / ".github/workflows/pr.yml").read_text(encoding="utf-8")


def push_workflow_jobs() -> dict[str, dict]:
    """Return push.yml's jobs, parsed, keyed by job id."""
    return yaml.safe_load(push_workflow())["jobs"]


def job_needs(job: dict) -> list[str]:
    """Return the ids of the jobs ``job`` needs, as a list."""
    needs = job.get("needs") or []
    if isinstance(needs, str):
        return [needs]
    return list(needs)


def job_step(job: dict, step_name: str) -> dict:
    """Return the step of ``job`` named ``step_name``."""
    matching_steps = [step for step in job["steps"] if step.get("name") == step_name]
    assert len(matching_steps) == 1, f"expected one step named {step_name}"
    return matching_steps[0]


def workflow_job_block(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"Missing workflow job {job_name}"
    return match.group("body")
