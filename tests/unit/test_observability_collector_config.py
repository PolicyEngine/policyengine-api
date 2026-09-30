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
    assert "print-identity-token" in verify_script
    assert "print-access-token" in verify_script
    assert "uv run --no-project" in verify_script
    assert "cloudtrace.googleapis.com" in verifier
    assert "monitoring.googleapis.com" in verifier
    assert "--format=json" in deploy_script
    assert 'select(.type == "Ready")' in deploy_script
    assert 'status.latestReadyRevisionName // ""' in deploy_script
    assert 'status.url // ""' in deploy_script
    assert "delivery_timeout_seconds: float = 600.0" in verifier
