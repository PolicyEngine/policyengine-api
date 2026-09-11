"""Exercise automatic bundle updates without GitHub or registry mutations."""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/update-policyengine-package.sh"


@pytest.fixture
def update_checkout(tmp_path):
    (tmp_path / "docker").mkdir()
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["policyengine[models]==5.2.0", '
        '"spm-calculator==0.3.1"]\n'
    )
    (tmp_path / "docker/Dockerfile").write_text(
        'FROM python:3.12\nRUN pip install "policyengine[models]==5.2.0" '
        "spm-calculator==0.3.1 ipython\n"
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
if name == "uv" and args[:1] == ["run"]:
    print("POLICYENGINE_VERSION=5.3.0")
"""
    for name in ("git", "gh", "uv"):
        path = binaries / name
        path.write_text(stub)
        path.chmod(0o755)
    return tmp_path


def run_update(root):
    log = root / "calls.jsonl"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=root,
        env={
            **os.environ,
            "PATH": f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "LATEST_OVERRIDE": "5.3.0",
            "BUNDLE_TEST_CALLS": str(log),
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
        assert "policyengine[models]==5.3.0" in text
        assert "policyengine[models]==5.2.0" not in text
        assert "spm-calculator==0.3.1" in text
    assert [
        "git",
        "add",
        "pyproject.toml",
        "docker/Dockerfile",
        "uv.lock",
        "changelog.d/update-policyengine-bundle-5.3.0.changed.md",
    ] in calls
    assert ["uv", "lock", "--upgrade-package", "policyengine"] in calls


@pytest.mark.parametrize("pin", ["5.1.0", "5.2.01", "5.2.0rc1"])
def test_mismatched_image_pin_fails_before_file_changes(update_checkout, pin):
    image = update_checkout / "docker/Dockerfile"
    image.write_text(image.read_text().replace("5.2.0", pin))
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
