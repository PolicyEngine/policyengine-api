from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
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
    assert 'jsonPayload."service.namespace"' in routing


def test_deployment_templates_use_environment_placeholders() -> None:
    templates = [
        DEPLOY / "iam.template.yaml",
        DEPLOY / "workload-inventory.template.yaml",
        DEPLOY / "log-routing.template.yaml",
        DEPLOY / "alerts.template.yaml",
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


def test_deployment_renderer_validates_and_does_not_print_values(
    tmp_path: Path,
) -> None:
    values = {
        "OBSERVABILITY_PROJECT_ID": "central-observability",
        "OBSERVABILITY_PROJECT_NUMBER": "123456789012",
        "API_PROJECT_ID": "api-project",
        "SIMULATION_ENTRY_PROJECT_ID": "simulation-entry-project",
        "MODAL_WORKSPACE_ID": "ac-private-workspace",
    }
    environment = os.environ.copy()
    environment.update(values)
    result = subprocess.run(
        [
            sys.executable,
            str(DEPLOY / "render_deployment.py"),
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert all(value not in result.stdout for value in values.values())
    rendered_iam = (tmp_path / "iam.yaml").read_text()
    assert "policyengine-otel-collector@central-observability" in rendered_iam
    assert 'assertion.workspace_id == "ac-private-workspace"' in rendered_iam
    assert stat.S_IMODE((tmp_path / "iam.yaml").stat().st_mode) == 0o600
    json.loads((tmp_path / "dashboard.json").read_text())


def test_deployment_renderer_rejects_missing_values(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for variable in (
        "OBSERVABILITY_PROJECT_ID",
        "OBSERVABILITY_PROJECT_NUMBER",
        "API_PROJECT_ID",
        "SIMULATION_ENTRY_PROJECT_ID",
        "MODAL_WORKSPACE_ID",
    ):
        environment.pop(variable, None)

    result = subprocess.run(
        [
            sys.executable,
            str(DEPLOY / "render_deployment.py"),
            "--output-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert "Missing deployment variables:" in result.stderr
    assert not list(tmp_path.iterdir())


def test_verification_script_has_valid_shell_syntax() -> None:
    subprocess.run(
        ["bash", "-n", str(DEPLOY / "verify.sh")],
        check=True,
        capture_output=True,
        text=True,
    )
