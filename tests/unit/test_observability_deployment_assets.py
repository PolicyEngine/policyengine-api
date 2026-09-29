from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
DEPLOY = ROOT / "gcp" / "observability"


def test_dashboard_is_valid_json_with_required_signals() -> None:
    dashboard = json.loads((DEPLOY / "dashboard.template.json").read_text())
    serialized = json.dumps(dashboard)
    assert "policyengine.request.count" in serialized
    assert "policyengine.request.duration" in serialized
    assert "policyengine.error.count" in serialized
    assert "policyengine.telemetry.dropped" in serialized
    assert "policyengine.telemetry.exporter.failure" in serialized


def test_collector_accepts_only_traces_and_metrics() -> None:
    config = (DEPLOY / "collector" / "config.yaml").read_text()
    assert "telemetry.googleapis.com:443" in config
    assert "memory_limiter" in config
    assert "googleclientauth" in config
    assert "    traces:" in config
    assert "    metrics:" in config
    assert "    logs:\n      receivers:" not in config


def test_authorization_assets_exclude_unrelated_applications() -> None:
    iam = (DEPLOY / "iam.template.yaml").read_text()
    routing = (DEPLOY / "log-routing.template.yaml").read_text()
    for excluded in (
        "policyengine-household-api",
        "policyengine-uk-chat",
        "peukchat",
        "precompute",
        "smoke",
        "ephemeral",
    ):
        assert excluded not in iam
        assert excluded not in routing
    assert "policyengine-simulation-gateway" in iam
    assert "policyengine-simulation-py" in iam
    assert "policyengine-simulation-v2-py" in iam
    assert "policyengine-simulation-v2-py" in routing
    assert 'jsonPayload."service.namespace"' in routing


def test_stage12_modal_apps_are_in_the_workload_identity_allowlist() -> None:
    iam = (DEPLOY / "iam.template.yaml").read_text()
    inventory = (DEPLOY / "workload-inventory.template.yaml").read_text()
    routing = (DEPLOY / "log-routing.template.yaml").read_text()
    stage12_pattern = "^policyengine-simulation-v2-py[0-9]+-[0-9]+-[0-9]+$"

    assert stage12_pattern in iam
    assert stage12_pattern in inventory
    assert stage12_pattern in routing


def test_cloud_run_source_sinks_route_every_log_from_exact_services() -> None:
    routing = (DEPLOY / "log-routing.template.yaml").read_text()
    source_sinks, direct_sink = routing.split("central_direct_sink:", 1)

    assert 'resource.type="cloud_run_revision"' in source_sinks
    for service_name in (
        "policyengine-api",
        "policyengine-api-staging",
        "policyengine-simulation-entry",
        "policyengine-simulation-entry-staging",
    ):
        assert f'resource.labels.service_name="{service_name}"' in source_sinks
    assert "jsonPayload.schema_version" not in source_sinks
    assert 'jsonPayload.schema_version="policyengine.observability.v2"' in direct_sink


def test_deployment_templates_use_environment_placeholders() -> None:
    templates = [
        DEPLOY / "iam.template.yaml",
        DEPLOY / "workload-inventory.template.yaml",
        DEPLOY / "log-routing.template.yaml",
        DEPLOY / "dashboard.template.json",
        DEPLOY / "collector" / "service.template.yaml",
    ]
    content = "\n".join(path.read_text() for path in templates)
    for variable in (
        "OBSERVABILITY_PROJECT_ID",
        "OBSERVABILITY_PROJECT_NUMBER",
        "API_PROJECT_ID",
        "SIMULATION_ENTRY_PROJECT_ID",
        "MODAL_WORKSPACE_ID",
    ):
        assert f"${{{variable}}}" in content
    assert "workspace_id: ac-" not in content
