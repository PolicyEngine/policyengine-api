"""Tests for .github/scripts/relock_dependencies.sh and locked_packages.py.

The relock upgrades every package in uv.lock except the PolicyEngine .py
bundle (``policyengine``) and the packages its extras pin, which move only
through the bundle update workflow. A fake ``uv`` stands in for resolution, so
the tests need no network access.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RELOCK_SCRIPT = REPO / ".github/scripts/relock_dependencies.sh"
LOCKED_PACKAGES_SCRIPT = REPO / ".github/scripts/locked_packages.py"
REGISTRY_SOURCE = '{ registry = "https://pypi.org/simple" }'
BUNDLE_PINS = (
    "policyengine-core",
    "policyengine-uk",
    "policyengine-us",
    "spm-calculator",
)

FAKE_UV = f"""#!{sys.executable}
import json
import os
import shutil
import sys

arguments = sys.argv[1:]
with open(os.environ["RELOCK_TEST_CALLS"], "a") as calls:
    calls.write(json.dumps(["uv", *arguments]) + "\\n")
if arguments[:1] == ["lock"] and "--check" in arguments:
    sys.exit(int(os.environ.get("RELOCK_TEST_CHECK_EXIT", "0")))
if arguments[:1] == ["lock"]:
    relocked = os.environ.get("RELOCK_TEST_RELOCKED")
    if relocked:
        shutil.copyfile(relocked, "uv.lock")
    sys.exit(int(os.environ.get("RELOCK_TEST_LOCK_EXIT", "0")))
"""


def _package(
    name: str,
    version: str,
    *,
    source: str = REGISTRY_SOURCE,
    extras: dict[str, tuple[str, ...]] | None = None,
) -> str:
    entry = f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {source}\n'
    for extra_name, members in (extras or {}).items():
        listed = "".join(f'    {{ name = "{member}" }},\n' for member in members)
        entry += f"\n[package.optional-dependencies]\n{extra_name} = [\n{listed}]\n"
    return entry


def _lock_text(*packages: str) -> str:
    header = 'version = 1\nrevision = 3\nrequires-python = ">=3.11"\n'
    return "\n".join([header, *packages])


def _project_lock(**versions: str) -> str:
    """Return a lock with the project, the bundle, its pins and other packages."""
    locked = {
        "numpy": "2.3.0",
        "pandas": "2.3.1",
        "policyengine": "6.7.5",
        "policyengine-core": "3.33.0",
        "policyengine-uk": "2.130.1",
        "policyengine-us": "2.2.1",
        "ruff": "0.15.12",
        "spm-calculator": "1.0.0",
    }
    locked.update({name.replace("_", "-"): value for name, value in versions.items()})
    entries = [_package("policyengine-api", "5.6.3", source='{ editable = "." }')]
    for name, version in sorted(locked.items()):
        if not version:
            continue
        extras = {"models": BUNDLE_PINS} if name == "policyengine" else None
        entries.append(_package(name, version, extras=extras))
    return _lock_text(*entries)


def _relock(
    checkout: Path,
    lock: str,
    *,
    relocked: str | None = None,
    **environment: str,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], str]:
    """Run the relock in ``checkout`` with a fake uv; return result, calls, outputs."""
    binaries = checkout / "bin"
    binaries.mkdir()
    fake_uv = binaries / "uv"
    fake_uv.write_text(FAKE_UV)
    fake_uv.chmod(0o755)
    (checkout / "uv.lock").write_text(lock)
    calls_log = checkout / "calls.jsonl"
    outputs = checkout / "github_output"
    run_environment = {
        **os.environ,
        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        "PYTHON": sys.executable,
        "GITHUB_OUTPUT": str(outputs),
        "RELOCK_SUMMARY_FILE": str(checkout / "summary.md"),
        "RELOCK_TEST_CALLS": str(calls_log),
    }
    run_environment.pop("RELOCK_PYTHON", None)
    run_environment.update(environment)
    if relocked is not None:
        relocked_lock = checkout / "relocked.lock"
        relocked_lock.write_text(relocked)
        run_environment["RELOCK_TEST_RELOCKED"] = str(relocked_lock)
    result = subprocess.run(
        ["bash", str(RELOCK_SCRIPT)],
        cwd=checkout,
        env=run_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = (
        [json.loads(call) for call in calls_log.read_text().splitlines()]
        if calls_log.exists()
        else []
    )
    written_outputs = outputs.read_text() if outputs.exists() else ""
    return result, calls, written_outputs


def _upgraded_packages(lock_call: list[str]) -> list[str]:
    return [
        lock_call[position + 1]
        for position, argument in enumerate(lock_call)
        if argument == "--upgrade-package"
    ]


def test_upgrades_every_package_except_the_bundle_and_its_pins(tmp_path: Path) -> None:
    lock = _project_lock() + "\n" + _package("numpy", "2.2.6")

    result, calls, _ = _relock(tmp_path, lock)

    assert result.returncode == 0, result.stderr
    lock_call, check_call = calls
    assert lock_call[:4] == ["uv", "lock", "--python", "3.12"]
    assert _upgraded_packages(lock_call) == ["numpy", "pandas", "ruff"]
    assert check_call == ["uv", "lock", "--check", "--python", "3.12"]


def test_resolves_with_the_requested_python(tmp_path: Path) -> None:
    result, calls, _ = _relock(tmp_path, _project_lock(), RELOCK_PYTHON="3.11")

    assert result.returncode == 0, result.stderr
    assert [call[:4] for call in calls] == [
        ["uv", "lock", "--python", "3.11"],
        ["uv", "lock", "--check", "--python"],
    ]
    assert calls[1][4] == "3.11"


def test_reports_no_change_when_the_lock_is_unchanged(tmp_path: Path) -> None:
    result, _, outputs = _relock(tmp_path, _project_lock())

    assert result.returncode == 0, result.stderr
    assert outputs.splitlines() == ["changed=false"]
    assert "uv.lock is unchanged" in result.stdout


def test_lists_version_changes_when_the_lock_changes(tmp_path: Path) -> None:
    relocked = _project_lock(numpy="2.3.1", ruff="", tzdata="2025.2")

    result, _, outputs = _relock(tmp_path, _project_lock(), relocked=relocked)

    assert result.returncode == 0, result.stderr
    assert outputs.splitlines() == ["changed=true"]
    summary = (tmp_path / "summary.md").read_text()
    assert "- `numpy`: 2.3.0 → 2.3.1" in summary
    assert "- `ruff`: no longer locked (was 0.15.12)" in summary
    assert "- `tzdata`: newly locked at 2025.2" in summary
    assert "pandas" not in summary.split("## Held")[0]
    assert "- `policyengine` 6.7.5" in summary
    assert "- `policyengine-us` 2.2.1" in summary


def test_fails_when_the_relock_moves_a_bundle_package(tmp_path: Path) -> None:
    relocked = _project_lock(numpy="2.3.1", policyengine_us="2.3.0")

    result, _, outputs = _relock(tmp_path, _project_lock(), relocked=relocked)

    assert result.returncode != 0
    assert "policyengine-us" in result.stderr
    assert "changed=" not in outputs


def test_stops_when_uv_lock_fails(tmp_path: Path) -> None:
    result, calls, outputs = _relock(
        tmp_path, _project_lock(), RELOCK_TEST_LOCK_EXIT="1"
    )

    assert result.returncode != 0
    assert len(calls) == 1
    assert "--check" not in calls[0]
    assert outputs == ""


def test_fails_when_the_lock_check_fails(tmp_path: Path) -> None:
    result, calls, outputs = _relock(
        tmp_path, _project_lock(), RELOCK_TEST_CHECK_EXIT="1"
    )

    assert result.returncode != 0
    assert len(calls) == 2
    assert outputs == ""


def test_fails_before_locking_when_the_bundle_is_not_locked(tmp_path: Path) -> None:
    lock = _lock_text(_package("numpy", "2.3.0"))

    result, calls, _ = _relock(tmp_path, lock)

    assert result.returncode != 0
    assert "policyengine is not locked" in result.stderr
    assert calls == []


def _locked_packages(command: str, lock: Path) -> list[str]:
    result = subprocess.run(
        [sys.executable, str(LOCKED_PACKAGES_SCRIPT), command, str(lock)],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.splitlines()


def test_the_repository_lock_holds_the_bundle_and_its_pinned_packages() -> None:
    held = {entry.split()[0] for entry in _locked_packages("held", REPO / "uv.lock")}
    upgradeable = set(_locked_packages("upgradeable", REPO / "uv.lock"))

    assert held == {"policyengine", *BUNDLE_PINS}
    assert not held & upgradeable
    assert "policyengine-api" not in upgradeable
    assert {"fastapi", "numpy", "policyengine-observability"} <= upgradeable
