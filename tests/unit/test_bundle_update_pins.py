"""Exercise automatic bundle updates without GitHub or registry mutations."""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/update-policyengine-package.sh"
SOURCE_VERSION = "4.0.0"
TARGET_VERSION = "4.1.0"


@pytest.fixture
def update_checkout(tmp_path):
    (tmp_path / "docker").mkdir()
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\ndependencies = ["policyengine[models]=={SOURCE_VERSION}"]\n'
    )
    (tmp_path / "docker/Dockerfile").write_text(
        "FROM python:3.12\n"
        f'RUN pip install "policyengine[models]=={SOURCE_VERSION}" ipython\n'
    )
    (tmp_path / "uv.lock").write_text("# registry resolution is stubbed\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    stub = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["BUNDLE_TEST_CALLS"], "a") as stream:
    stream.write(json.dumps([name, *args]) + "\\n")
if name == "git" and args[:1] == ["ls-remote"]:
    sys.exit(2)
if name == "gh" and args[:2] == ["pr", "view"]:
    if os.environ.get("BUNDLE_TEST_OPEN_PR"):
        print(os.environ["BUNDLE_TEST_OPEN_PR"])
        sys.exit(0)
    sys.exit(1)
if name == "uv" and args[:2] == ["lock", "--upgrade-package"]:
    if os.environ.get("BUNDLE_TEST_LOCK_FAIL"):
        sys.exit(1)
if name == "uv" and args[:1] == ["run"]:
    reported = os.environ.get("BUNDLE_TEST_REPORTED_VERSION", "4.1.0")
    print(f"POLICYENGINE_VERSION={reported}")
    print("POLICYENGINE_CORE_VERSION=3.0.0")
    print("US_VERSION=2.0.0")
    print("UK_VERSION=2.1.0")
    print("SPM_CALCULATOR_VERSION=1.0.0")
    print("US_DATA_VERSION=us-data-release")
    print("UK_DATA_VERSION=uk-data-release")
"""
    for name in ("git", "gh", "uv"):
        path = binaries / name
        path.write_text(stub)
        path.chmod(0o755)
    return tmp_path


def run_update(root, *arguments, **environment):
    log = root / "calls.jsonl"
    result = subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        cwd=root,
        env={
            **os.environ,
            "PATH": f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "LATEST_OVERRIDE": TARGET_VERSION,
            "BUNDLE_TEST_CALLS": str(log),
            "LOCK_RETRY_SECONDS": "0",
            **environment,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, calls


def test_automatic_update_changes_and_stages_both_image_pins(update_checkout):
    result, calls = run_update(update_checkout)
    assert result.returncode == 0, result.stderr
    for name in ("pyproject.toml", "docker/Dockerfile"):
        text = (update_checkout / name).read_text()
        assert f"policyengine[models]=={TARGET_VERSION}" in text
        assert f"policyengine[models]=={SOURCE_VERSION}" not in text
        assert "spm-calculator==" not in text
    assert [
        "git",
        "add",
        "pyproject.toml",
        "docker/Dockerfile",
        "uv.lock",
        f"changelog.d/update-policyengine-bundle-{TARGET_VERSION}.changed.md",
    ] in calls
    assert ["uv", "lock", "--upgrade-package", "policyengine"] in calls
    assert ["uv", "lock", "--check"] in calls
    assert [
        "uv",
        "run",
        "--frozen",
        "python",
        ".github/find-api-model-versions.py",
        "--shell",
    ] in calls


@pytest.mark.parametrize("pin", ["3.9.0", "4.0.01", "4.0.0rc1"])
def test_mismatched_image_pin_fails_before_file_changes(update_checkout, pin):
    image = update_checkout / "docker/Dockerfile"
    image.write_text(image.read_text().replace(SOURCE_VERSION, pin))
    before = {
        name: (update_checkout / name).read_bytes()
        for name in ("pyproject.toml", "docker/Dockerfile")
    }
    result, calls = run_update(update_checkout)
    assert result.returncode != 0
    assert "Expected one matching" in result.stderr
    for name, data in before.items():
        assert (update_checkout / name).read_bytes() == data
    assert not any(call[:1] == ["uv"] for call in calls)
    assert not any(call[:2] == ["git", "commit"] for call in calls)


def test_dry_run_does_not_change_files(update_checkout):
    before = {
        name: (update_checkout / name).read_bytes()
        for name in ("pyproject.toml", "docker/Dockerfile", "uv.lock")
    }
    result, calls = run_update(update_checkout, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "Dry run complete" in result.stdout
    for name, data in before.items():
        assert (update_checkout / name).read_bytes() == data
    assert not any(call[:1] == ["uv"] for call in calls)


def test_lock_failure_stops_before_commit(update_checkout):
    result, calls = run_update(update_checkout, BUNDLE_TEST_LOCK_FAIL="1")
    assert result.returncode != 0
    assert "uv lock failed after 3 attempts" in result.stderr
    assert sum(
        call == ["uv", "lock", "--upgrade-package", "policyengine"]
        for call in calls
    ) == 3
    assert not any(call[:2] == ["git", "commit"] for call in calls)


def test_manifest_version_mismatch_stops_before_commit(update_checkout):
    result, calls = run_update(
        update_checkout, BUNDLE_TEST_REPORTED_VERSION="4.0.9"
    )
    assert result.returncode != 0
    assert "does not match requested version" in result.stderr
    assert not any(call[:2] == ["git", "commit"] for call in calls)


def test_existing_pull_request_is_found_by_exact_branch(update_checkout):
    result, calls = run_update(update_checkout, BUNDLE_TEST_OPEN_PR="321")
    assert result.returncode == 0, result.stderr
    assert "PR #321 already exists" in result.stdout
    assert [
        "gh",
        "pr",
        "view",
        f"auto/update-policyengine-bundle-{TARGET_VERSION}",
        "--json",
        "number,state",
        "--jq",
        'select(.state == "OPEN") | .number',
    ] in calls
    assert not any(call[:1] == ["uv"] for call in calls)
