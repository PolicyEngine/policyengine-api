"""Building the image and deploying a Cloud Run candidate revision (dry runs)."""

from __future__ import annotations

import pytest

from tests.unit.cloud_run_deploy_support import (
    PRODUCTION_CLOUD_SQL_INSTANCE,
    PRODUCTION_DB_PASSWORD_SECRET,
    REPO,
    STAGING_CLOUD_RUN_SERVICE,
    TEST_AUTH0_SECRET_RESOURCE,
    TEST_OTEL_ENDPOINT,
    TEST_V2_ENVIRONMENT,
    TEST_V2_PROJECT_REF,
    TEST_V2_RUNTIME_SECRET_RESOURCE,
)
from tests.unit.cloud_run_deploy_support import (
    required_runtime_env as _required_runtime_env,
)
from tests.unit.cloud_run_deploy_support import (
    run_script as _run_script,
)
from tests.unit.cloud_run_deploy_support import (
    script_env as _script_env,
)

DEDICATED_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT = (
    "policyengine-api-cr-runtime@policyengine-api.iam.gserviceaccount.com"
)


CLOUD_RUN_SECRET_MAPPINGS = {
    "POLICYENGINE_DB_PASSWORD": PRODUCTION_DB_PASSWORD_SECRET,
    "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN": (
        "policyengine-api-prod-github-microdata-token:latest"
    ),
    "OPENAI_API_KEY": "policyengine-api-prod-openai-api-key:latest",
    "HUGGING_FACE_TOKEN": "pe-uk-private-hf-read-token:latest",
}


RAW_CLOUD_RUN_SECRET_VALUES = (
    "raw-db-secret-value",
    "raw-github-secret-value",
    "raw-openai-secret-value",
    "raw-hf-secret-value",
)


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


def test_deploy_cloud_run_candidate_dry_run_preserves_access_and_traffic():
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
    assert "--allow-unauthenticated" not in result.stdout
    assert "--no-allow-unauthenticated" not in result.stdout
    assert "--invoker-iam-check" not in result.stdout
    assert "stage3-test" in result.stdout
    assert (
        f"--service-account {DEDICATED_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT}"
        in result.stdout
    )
    assert f"--set-cloudsql-instances {PRODUCTION_CLOUD_SQL_INSTANCE}" in result.stdout
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
    assert "APP_ENVIRONMENT=production" in result.stdout
    assert f"OTEL_EXPORTER_OTLP_ENDPOINT={TEST_OTEL_ENDPOINT}" in result.stdout
    assert "OBSERVABILITY_SERVICE_NAMESPACE=policyengine.api-v1" in result.stdout
    assert "OBSERVABILITY_TRACE_PROJECT_ID=central-observability" in result.stdout
    assert "OTEL_EXPORTER_OTLP_PROTOCOL=grpc" in result.stdout
    assert "OTEL_TRACES_EXPORTER=otlp" in result.stdout
    assert "OTEL_METRICS_EXPORTER=otlp" in result.stdout
    assert "OTEL_TRACES_SAMPLER_ARG=1.0" in result.stdout
    assert f"POLICYENGINE_OTEL_GOOGLE_AUDIENCE={TEST_OTEL_ENDPOINT}" in result.stdout
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
    assert result.stdout.count("ROUTE_IMPL_POLICY=flask_fallback") == 1
    assert result.stdout.count("DB_READ_POLICY=cloud_sql") == 1
    assert result.stdout.count("DB_WRITE_POLICY=cloud_sql") == 1
    assert result.stdout.count("ROUTE_IMPL_HOUSEHOLD=flask_fallback") == 1
    assert result.stdout.count("DB_READ_HOUSEHOLD=cloud_sql") == 1
    assert result.stdout.count("DB_WRITE_HOUSEHOLD=cloud_sql") == 1


def test_deploy_cloud_run_candidate_passes_optional_startup_warmup_setting():
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
            POLICYENGINE_API_STARTUP_WARMUP="0",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "POLICYENGINE_API_STARTUP_WARMUP=0" in result.stdout


def test_deploy_cloud_run_candidate_uses_configured_database_instance():
    configured_instance = "project:region:configured-instance"
    env = {
        **_required_runtime_env(),
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": configured_instance,
        "PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": configured_instance,
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
    assert f"--set-cloudsql-instances {configured_instance}" in result.stdout
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
    routes live traffic onto it. Probing /health, which answers 503 until the
    warmup has finished and the runtime configuration is valid, makes Cloud
    Run withhold traffic until the app can actually serve.
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
    assert "httpGet.path=/health" in result.stdout
    assert "httpGet.port=8080" in result.stdout
    # A tcpSocket probe would reintroduce routing-before-ready.
    assert "tcpSocket" not in result.stdout

    probe = next(
        part for part in result.stdout.split() if "httpGet.path=/health" in part
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


def test_deploy_cloud_run_candidate_passes_user_auth_settings():
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "PUBLIC_API_AUTH_REQUIRED=1" in result.stdout
    assert "PUBLIC_API_AUTH_ISSUER=https://auth.example.test/" in result.stdout
    assert "PUBLIC_API_AUTH_AUDIENCE=https://api.policyengine.org/" in result.stdout
    assert "AUTH0_MANAGEMENT_DOMAIN" not in result.stdout

    with_management = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
            AUTH0_MANAGEMENT_DOMAIN="policyengine.us.auth0.com",
            AUTH0_MANAGEMENT_CLIENT_ID="management-client",
            AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE=TEST_AUTH0_SECRET_RESOURCE,
        ),
    )
    assert with_management.returncode == 0, with_management.stderr
    assert "AUTH0_MANAGEMENT_DOMAIN=policyengine.us.auth0.com" in with_management.stdout
    assert (
        f"AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE={TEST_AUTH0_SECRET_RESOURCE}"
        in with_management.stdout
    )
