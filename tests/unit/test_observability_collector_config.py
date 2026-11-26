from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
DEPLOY = ROOT / "gcp" / "observability"


def test_collector_accepts_only_traces_and_metrics() -> None:
    config = (DEPLOY / "collector" / "config.yaml").read_text()
    assert "telemetry.googleapis.com:443" in config
    assert "memory_limiter" in config
    assert "googleclientauth" in config
    assert "    traces:" in config
    assert "    metrics:" in config
    assert "    logs:\n      receivers:" not in config


def test_collector_assigns_metric_location_without_overwriting_trace_region() -> None:
    config = yaml.safe_load(
        (DEPLOY / "collector" / "config.yaml").read_text(encoding="utf-8")
    )

    location = config["processors"]["resource/metric_location"]["attributes"]
    assert location == [
        {
            "key": "location",
            "value": "${env:OBSERVABILITY_METRIC_LOCATION}",
            "action": "upsert",
        }
    ]
    assert (
        "resource/metric_location"
        in config["service"]["pipelines"]["metrics"]["processors"]
    )
    assert (
        "resource/metric_location"
        not in config["service"]["pipelines"]["traces"]["processors"]
    )


def test_collector_has_repeatable_authenticated_deployment() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "deploy-observability-collector.yml"
    ).read_text(encoding="utf-8")
    deploy_script = (
        ROOT / ".github" / "scripts" / "deploy_observability_collector.sh"
    ).read_text(encoding="utf-8")
    verify_script = (
        ROOT / ".github" / "scripts" / "verify_observability_collector.sh"
    ).read_text(encoding="utf-8")
    verifier = (
        ROOT / ".github" / "scripts" / "verify_observability_collector.py"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "push:" in workflow
    assert "- master" in workflow
    assert '"gcp/observability/collector/**"' in workflow
    assert '".github/scripts/deploy_observability_collector.sh"' in workflow
    assert '".github/scripts/verify_observability_collector.sh"' in workflow
    assert '".github/scripts/verify_observability_collector.py"' in workflow
    assert '".github/workflows/deploy-observability-collector.yml"' in workflow
    assert "environment: production" in workflow
    assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in workflow
    assert "GCP_DEPLOY_SERVICE_ACCOUNT" in workflow
    assert "validate --config=" in workflow
    assert "bash .github/scripts/deploy_observability_collector.sh" in workflow
    assert "bash .github/scripts/verify_observability_collector.sh" in workflow
    assert ":${GITHUB_SHA}" in deploy_script
    assert "--invoker-iam-check" in deploy_script
    assert "remove-iam-policy-binding" in deploy_script
    assert "allUsers allAuthenticatedUsers" in deploy_script
    assert "invoker-iam-disabled" in deploy_script
    assert "--use-http2" in deploy_script
    assert "OBSERVABILITY_METRIC_LOCATION" in deploy_script
    assert "httpGet.port=13133" in deploy_script
    assert "TraceServiceStub" in verifier
    assert "MetricsServiceStub" in verifier
    assert "LogsServiceStub" in verifier
    assert "StatusCode.UNIMPLEMENTED" in verifier
    assert "print-identity-token" not in verify_script
    assert "COLLECTOR_ID_TOKEN" in verify_script
    assert "print-access-token" in verify_script
    assert "uv run --no-project" in verify_script
    assert "cloudtrace.googleapis.com" in verifier
    assert "monitoring.googleapis.com" in verifier
    assert "--format=json" in deploy_script
    assert 'select(.type == "Ready")' in deploy_script
    assert 'status.latestReadyRevisionName // ""' in deploy_script
    assert 'status.url // ""' in deploy_script
    assert "delivery_timeout_seconds: float = 600.0" in verifier


def _collector_deploy_steps() -> list[dict]:
    workflow_file = "deploy-observability-collector.yml"
    workflow_path = ROOT / ".github" / "workflows" / workflow_file
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    return workflow["jobs"]["deploy"]["steps"]


def test_collector_verification_gets_its_identity_token_from_the_auth_action() -> None:
    """A second auth step mints the identity token the verification step uses.

    gcloud can't mint an identity token with an audience from a workload
    identity federation credential, so the step mints it for the deployed
    collector's URL and the verification step reads it from that step's output.
    """
    steps = _collector_deploy_steps()
    names = [step.get("name") for step in steps]
    token_step = next(step for step in steps if step.get("id") == "collector_token")
    verify_step = next(
        step
        for step in steps
        if "verify_observability_collector.sh" in step.get("run", "")
    )

    assert token_step["uses"] == "google-github-actions/auth@v2"
    assert token_step["with"] == {
        "workload_identity_provider": "${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}",
        "service_account": "${{ secrets.GCP_DEPLOY_SERVICE_ACCOUNT }}",
        "token_format": "id_token",
        "id_token_audience": "${{ steps.collector.outputs.service_url }}",
        "id_token_include_email": True,
        "create_credentials_file": False,
        "export_environment_variables": False,
    }
    assert names.index(token_step["name"]) > names.index("Build and deploy collector")
    assert names.index(token_step["name"]) < names.index(verify_step["name"])
    assert verify_step["env"] == {
        "COLLECTOR_ID_TOKEN": "${{ steps.collector_token.outputs.id_token }}"
    }
