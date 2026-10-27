"""When the deployed policyengine.py version went live (deploy script and route)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from policyengine_api.asgi_factory import create_asgi_app
from tests.unit.cloud_run_deploy_support import (
    PRODUCTION_CLOUD_RUN_SERVICE,
    required_runtime_env,
    run_script,
    script_env,
)
from tests.unit.test_asgi_factory import create_test_wsgi_app

if TYPE_CHECKING:
    from pathlib import Path

SCRIPT = ".github/scripts/resolve_policyengine_live_since.sh"
NOW = "2026-10-28T09:00:00Z"
EARLIER = "2026-10-20T12:00:00Z"


def _lock(tmp_path: Path, version: str) -> Path:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        "version = 1\n\n"
        '[[package]]\nname = "policyengine"\n'
        f'version = "{version}"\n\n'
        '[[package]]\nname = "policyengine-us"\nversion = "2.2.1"\n',
        encoding="utf-8",
    )
    return lock


def _fake_gcloud(tmp_path: Path, revision_env: dict[str, str] | None) -> Path:
    """Write a gcloud that describes one revision with revision_env, or fails."""
    calls = tmp_path / "gcloud-calls.json"
    gcloud = tmp_path / "gcloud"
    body = (
        "sys.exit('describe failed')"
        if revision_env is None
        else "print(json.dumps({'spec': {'containers': [{'env': ENV}]}}))"
    )
    env_items = [
        {"name": name, "value": value} for name, value in (revision_env or {}).items()
    ]
    gcloud.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"ENV = {env_items!r}\n"
        f"pathlib.Path({str(calls)!r}).write_text(json.dumps(sys.argv[1:]))\n"
        f"{body}\n",
        encoding="utf-8",
    )
    gcloud.chmod(0o755)
    return gcloud


def _resolve(
    tmp_path: Path,
    *,
    version: str = "6.11.1",
    previous: str = "policyengine-api-00001-old",
    revision_env: dict[str, str] | None = None,
    dry_run: bool = False,
):
    gcloud = _fake_gcloud(tmp_path, revision_env)
    return run_script(
        SCRIPT,
        script_env(
            CLOUD_RUN_DRY_RUN="1" if dry_run else "0",
            CLOUD_RUN_SERVICE=PRODUCTION_CLOUD_RUN_SERVICE,
            GCLOUD_BIN=str(gcloud),
            POLICYENGINE_LOCK_FILE=str(_lock(tmp_path, version)),
            POLICYENGINE_LIVE_SINCE_NOW=NOW,
            PREVIOUS_CLOUD_RUN_REVISION=previous,
        ),
    )


def _outputs(result) -> dict[str, str]:
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def test_same_version_keeps_the_serving_revisions_date(tmp_path):
    result = _resolve(
        tmp_path,
        revision_env={
            "DEPLOYED_POLICYENGINE_VERSION": "6.11.1",
            "POLICYENGINE_VERSION_LIVE_SINCE": EARLIER,
        },
    )

    assert _outputs(result) == {
        "DEPLOYED_POLICYENGINE_VERSION": "6.11.1",
        "POLICYENGINE_VERSION_LIVE_SINCE": EARLIER,
    }
    args = json.loads((tmp_path / "gcloud-calls.json").read_text())
    assert args[:4] == ["run", "revisions", "describe", "policyengine-api-00001-old"]


def test_new_version_goes_live_with_this_deploy(tmp_path):
    result = _resolve(
        tmp_path,
        revision_env={
            "DEPLOYED_POLICYENGINE_VERSION": "6.10.0",
            "POLICYENGINE_VERSION_LIVE_SINCE": EARLIER,
        },
    )

    assert _outputs(result)["POLICYENGINE_VERSION_LIVE_SINCE"] == NOW


def test_a_first_deploy_goes_live_with_this_deploy(tmp_path):
    result = _resolve(tmp_path, previous="", revision_env={})

    assert _outputs(result)["POLICYENGINE_VERSION_LIVE_SINCE"] == NOW


@pytest.mark.parametrize(
    "revision_env",
    [
        pytest.param({}, id="revision from before versions were recorded"),
        pytest.param(
            {"DEPLOYED_POLICYENGINE_VERSION": "6.11.1"},
            id="same version without a recorded date",
        ),
        pytest.param(None, id="describe fails"),
    ],
)
def test_an_unknown_start_stays_unknown_rather_than_wrong(tmp_path, revision_env):
    result = _resolve(tmp_path, revision_env=revision_env)

    assert _outputs(result) == {
        "DEPLOYED_POLICYENGINE_VERSION": "6.11.1",
        "POLICYENGINE_VERSION_LIVE_SINCE": "",
    }


def test_a_lock_without_policyengine_fails(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "numpy"\nversion = "2.1.0"\n')

    result = run_script(
        SCRIPT,
        script_env(POLICYENGINE_LOCK_FILE=str(lock)),
    )

    assert result.returncode != 0
    assert "policyengine is not locked" in result.stderr


def test_the_candidate_deploy_sets_both_variables():
    result = run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        script_env(
            **required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
            POLICYENGINE_LIVE_SINCE_NOW=NOW,
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "DEPLOYED_POLICYENGINE_VERSION=" in result.stdout
    assert f"POLICYENGINE_VERSION_LIVE_SINCE={NOW}" in result.stdout


def test_the_deployment_route_reports_version_date_and_revision(monkeypatch):
    monkeypatch.setenv("POLICYENGINE_VERSION_LIVE_SINCE", EARLIER)
    monkeypatch.setenv("K_REVISION", "policyengine-api-00042-abc")
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    body = client.get("/deployment").json()

    assert body["policyengine_version_live_since"] == EARLIER
    assert body["revision"] == "policyengine-api-00042-abc"
    assert body["policyengine_version"]


def test_the_deployment_route_has_no_date_before_the_deploy_records_one(
    monkeypatch,
):
    monkeypatch.delenv("POLICYENGINE_VERSION_LIVE_SINCE", raising=False)
    client = TestClient(create_asgi_app(create_test_wsgi_app()))

    assert client.get("/deployment").json()["policyengine_version_live_since"] is None
