"""Tests for .github/scripts/verify_observability_collector.sh.

The script runs with stand-in ``gcloud`` and ``uv`` commands first on ``PATH``,
which record how they were called instead of contacting Google Cloud.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/verify_observability_collector.sh"
ENDPOINT = "https://collector.example.run.app"


def _stand_in_commands(tmp_path: Path) -> tuple[Path, Path]:
    """Write stand-in gcloud and uv commands that log their calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "gcloud $*" >> "{calls}"\n'
        'if [[ "$*" == "auth print-access-token" ]]; then\n'
        "  echo access-token-from-gcloud\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "uv $*" >> "{calls}"\n'
        f'echo "uv saw COLLECTOR_ID_TOKEN=${{COLLECTOR_ID_TOKEN:-}}" >> "{calls}"\n'
        'echo "uv saw GOOGLE_OAUTH_ACCESS_TOKEN=${GOOGLE_OAUTH_ACCESS_TOKEN:-}"'
        f' >> "{calls}"\n'
    )
    for command in (gcloud, uv):
        command.chmod(0o755)
    return bin_dir, calls


def _run(
    tmp_path: Path, *arguments: str, collector_id_token: str | None
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir, calls = _stand_in_commands(tmp_path)
    environment = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "OBSERVABILITY_PROJECT_ID": "observability-project",
        "OBSERVABILITY_METRIC_LOCATION": "us-central1",
    }
    if collector_id_token is not None:
        environment["COLLECTOR_ID_TOKEN"] = collector_id_token
    result = subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    logged = calls.read_text().splitlines() if calls.exists() else []
    return result, logged


def test_passes_the_workflow_identity_token_to_the_verifier(tmp_path: Path) -> None:
    result, logged = _run(tmp_path, ENDPOINT, collector_id_token="token-from-auth-step")

    assert result.returncode == 0, result.stderr
    gcloud_calls = [line for line in logged if line.startswith("gcloud ")]
    assert gcloud_calls == ["gcloud auth print-access-token"]
    assert "uv saw COLLECTOR_ID_TOKEN=token-from-auth-step" in logged
    assert "uv saw GOOGLE_OAUTH_ACCESS_TOKEN=access-token-from-gcloud" in logged
    verifier_call = next(line for line in logged if line.startswith("uv run "))
    assert f"--endpoint {ENDPOINT}" in verifier_call
    assert "--project-id observability-project" in verifier_call
    assert "--metric-location us-central1" in verifier_call
    assert "::add-mask::token-from-auth-step" in result.stdout
    assert "::add-mask::access-token-from-gcloud" in result.stdout


def test_fails_without_an_identity_token_and_runs_nothing(tmp_path: Path) -> None:
    result, logged = _run(tmp_path, ENDPOINT, collector_id_token=None)

    assert result.returncode != 0
    assert "COLLECTOR_ID_TOKEN" in result.stderr
    assert logged == []


def test_fails_without_an_endpoint(tmp_path: Path) -> None:
    result, logged = _run(tmp_path, collector_id_token="token-from-auth-step")

    assert result.returncode != 0
    assert "Usage:" in result.stderr
    assert logged == []
