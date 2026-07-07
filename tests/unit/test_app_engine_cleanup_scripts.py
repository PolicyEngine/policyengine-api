"""Unit tests for the App Engine idle-version cleanup scripts.

`cleanup_app_engine_versions.sh` and `stop_app_engine_version.sh` are exercised
by running them under bash with a stubbed ``gcloud`` on ``PATH`` (mirroring the
approach in ``test_cloud_run_deploy_scripts.py``). The stub returns canned
``gcloud app versions list`` output based on the ``--filter`` and records any
``stop``/``delete`` invocations, so the tests assert the selection logic without
touching real infrastructure. All cleanup runs use ``DRY_RUN=1``.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLEANUP_SCRIPT = ".github/scripts/cleanup_app_engine_versions.sh"
STOP_SCRIPT = ".github/scripts/stop_app_engine_version.sh"
CR_IMAGES_SCRIPT = ".github/scripts/cleanup_cloud_run_images.sh"

# A stub `gcloud` that answers `app versions list` from MOCK_* env vars (each a
# newline-joined, newest-first id list) and appends any stop/delete calls to
# $GCLOUD_CALLS so tests can assert nothing mutating ran under DRY_RUN.
_FAKE_GCLOUD = """#!/usr/bin/env bash
filter=""
for a in "$@"; do
  case "$a" in --filter=*) filter="${a#--filter=}";; esac
done
case "$*" in
  *"artifacts docker images list"*) [ -n "${MOCK_AR_IMAGES:-}" ] && printf '%s\\n' "$MOCK_AR_IMAGES";;
  *"artifacts docker images delete"*) echo "IMG_DELETE $*" >> "$GCLOUD_CALLS";;
  *"versions list"*)
    case "$filter" in
      *"traffic_split>0"*) [ -n "${MOCK_TRAFFIC:-}" ] && printf '%s\\n' "$MOCK_TRAFFIC";;
      *"servingStatus=SERVING"*) [ -n "${MOCK_SERVING:-}" ] && printf '%s\\n' "$MOCK_SERVING";;
      *"servingStatus=STOPPED"*) [ -n "${MOCK_STOPPED:-}" ] && printf '%s\\n' "$MOCK_STOPPED";;
    esac;;
  *"versions stop"*)   echo "STOP $*" >> "$GCLOUD_CALLS";;
  *"versions delete"*) echo "DELETE $*" >> "$GCLOUD_CALLS";;
esac
exit 0
"""


def _run(
    script: str,
    tmp_path: Path,
    *,
    serving: list[str] | None = None,
    traffic: list[str] | None = None,
    stopped: list[str] | None = None,
    ar_images: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    gcloud = stub_dir / "gcloud"
    gcloud.write_text(_FAKE_GCLOUD, encoding="utf-8")
    gcloud.chmod(0o755)

    calls = tmp_path / "gcloud_calls.log"
    calls.write_text("", encoding="utf-8")

    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": f"{stub_dir}:{os.environ['PATH']}",
        "DRY_RUN": "1",
        "APP_ENGINE_PROJECT": "test-project",
        "GCLOUD_CALLS": str(calls),
        "MOCK_SERVING": "\n".join(serving or []),
        "MOCK_TRAFFIC": "\n".join(traffic or []),
        "MOCK_STOPPED": "\n".join(stopped or []),
        "MOCK_AR_IMAGES": "\n".join(ar_images or []),
    }
    env.update(extra_env or {})

    result = subprocess.run(
        ["bash", script],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, calls


def _list_after(label: str, stdout: str) -> list[str]:
    """Return the space-separated ids printed after a `Label[ (n)]: ...` line."""
    match = re.search(rf"{re.escape(label)}(?: \(\d+\))?:\s*(.*)", stdout)
    assert match is not None, f"missing '{label}' line in:\n{stdout}"
    body = match.group(1).strip()
    return [] if body == "<none>" else body.split()


# --- syntax --------------------------------------------------------------


def test_cleanup_scripts_are_shell_syntax_valid():
    for script in (CLEANUP_SCRIPT, STOP_SCRIPT, CR_IMAGES_SCRIPT):
        result = subprocess.run(
            ["bash", "-n", script], cwd=REPO, capture_output=True, text=True
        )
        assert result.returncode == 0, f"{script}: {result.stderr}"


# --- cloud run image cleanup (keep 15) -----------------------------------

_CR_PKG = (
    "us-central1-docker.pkg.dev/policyengine-api/policyengine-api/policyengine-api"
)


def _ar_rows(digests: list[str], package: str = _CR_PKG) -> list[str]:
    """`createTime|package|version` rows, oldest first (day 01 = oldest). The
    script sorts by createTime descending itself, so order here is irrelevant."""
    return [
        f"2026-01-{i + 1:02d}T00:00:00|{package}|sha256:{d}"
        for i, d in enumerate(digests)
    ]


def test_cloud_run_images_keeps_newest_15(tmp_path):
    digests = [f"d{i:02d}" for i in range(18)]  # d00 oldest ... d17 newest
    result, calls = _run(CR_IMAGES_SCRIPT, tmp_path, ar_images=_ar_rows(digests))
    assert result.returncode == 0, result.stderr
    assert "Images:    18 (keeping newest 15)" in result.stdout
    assert "Deleting:  3" in result.stdout
    # The 3 oldest digests are the ones deleted; the newest is kept.
    for old in ("sha256:d00", "sha256:d01", "sha256:d02"):
        assert f"would delete {_CR_PKG}@{old}" in result.stdout
    assert "sha256:d17" not in result.stdout.split("Deleting:")[1]
    assert calls.read_text() == ""  # DRY_RUN performs no mutations


def test_cloud_run_images_no_delete_when_within_keep(tmp_path):
    result, _ = _run(
        CR_IMAGES_SCRIPT, tmp_path, ar_images=_ar_rows([f"d{i}" for i in range(10)])
    )
    assert result.returncode == 0, result.stderr
    assert "Deleting:  0" in result.stdout
    assert "would delete" not in result.stdout


def test_cloud_run_images_respects_keep_override(tmp_path):
    result, _ = _run(
        CR_IMAGES_SCRIPT,
        tmp_path,
        ar_images=_ar_rows([f"d{i}" for i in range(10)]),
        extra_env={"KEEP": "5"},
    )
    assert "keeping newest 5" in result.stdout
    assert "Deleting:  5" in result.stdout


# --- app engine cleanup also prunes each deleted version's image ----------


def test_app_engine_cleanup_deletes_gae_flexible_image_per_deleted_version(tmp_path):
    result, _ = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=["prod-110", "prod-108"],
        traffic=["prod-110"],
        stopped=[f"prod-{n}" for n in range(106, 84, -2)]  # 11 prod -> 1 deleted
        + ["staging-90", "staging-88", "staging-86", "staging-84"],  # 1 deleted
    )
    assert result.returncode == 0, result.stderr
    deleted = _list_after("Deleting", result.stdout)
    assert deleted, "expected some versions to be deleted"
    # AR_IMAGE_PROJECT defaults to APP_ENGINE_PROJECT, which _run sets.
    repo = "us-central1-docker.pkg.dev/test-project/gae-flexible/default."
    # Every deleted version has a matching gae-flexible image deletion line.
    for v in deleted:
        assert f"would delete image {repo}{v}" in result.stdout
    # No image deletion for a kept (live/warm) version.
    assert f"{repo}prod-110" not in result.stdout


def test_app_engine_cleanup_image_pruning_can_be_disabled(tmp_path):
    result, _ = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=["prod-110", "prod-108"],
        traffic=["prod-110"],
        stopped=[f"prod-{n}" for n in range(106, 84, -2)],
        extra_env={"CLEANUP_APP_ENGINE_IMAGES": "0"},
    )
    assert result.returncode == 0, result.stderr
    assert "would delete image" not in result.stdout


# --- cleanup: stop selection ---------------------------------------------


def test_keeps_live_and_warm_prod_and_stops_the_rest(tmp_path):
    result, calls = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=["prod-110", "prod-108", "staging-110", "staging-108", "prod-106"],
        traffic=["prod-110"],
        stopped=["prod-104", "prod-102"],
    )
    assert result.returncode == 0, result.stderr
    assert _list_after("Serving traffic (never touched)", result.stdout) == ["prod-110"]
    assert _list_after("Keeping warm (rollback window)", result.stdout) == [
        "prod-110",
        "prod-108",
    ]
    # Every SERVING version except the live one and the 2 newest prod is stopped.
    assert _list_after("Stopping", result.stdout) == [
        "staging-110",
        "staging-108",
        "prod-106",
    ]
    # The live version is never in the stop or delete sets.
    assert "prod-110" not in _list_after("Stopping", result.stdout)
    assert "prod-110" not in _list_after("Deleting", result.stdout)
    # DRY_RUN performs no mutations.
    assert calls.read_text() == ""


def test_traffic_holder_is_protected_even_when_it_is_an_older_version(tmp_path):
    # Simulates a manual rollback: traffic sits on prod-106 while prod-110/108
    # are newer. The older, traffic-serving version must NOT be stopped.
    result, _ = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=["prod-110", "prod-108", "prod-106", "staging-110"],
        traffic=["prod-106"],
        stopped=[],
    )
    assert result.returncode == 0, result.stderr
    assert "prod-106" not in _list_after("Stopping", result.stdout)
    assert _list_after("Serving traffic (never touched)", result.stdout) == ["prod-106"]


# --- cleanup: delete selection / retention -------------------------------


def test_deletes_only_stopped_beyond_retention_window(tmp_path):
    stopped_prod = [f"prod-{n}" for n in range(120, 98, -2)]  # 11 prod, newest first
    stopped_staging = [f"staging-{n}" for n in range(120, 108, -2)]  # 6 staging
    legacy = ["20260101t120000", "20251201t120000"]
    result, _ = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=["prod-130"],
        traffic=["prod-130"],
        stopped=stopped_prod + stopped_staging + legacy,
    )
    assert result.returncode == 0, result.stderr

    kept_prod = _list_after("Keeping stopped prod", result.stdout)
    kept_staging = _list_after("Keeping stopped staging", result.stdout)
    deleted = _list_after("Deleting", result.stdout)

    assert kept_prod == stopped_prod[:10]  # newest 10 prod
    assert kept_staging == stopped_staging[:3]  # newest 3 staging
    # Everything else stopped is deleted: 1 oldest prod + 3 older staging + 2 legacy.
    assert set(deleted) == {stopped_prod[10]} | set(stopped_staging[3:]) | set(legacy)
    # Never deletes a SERVING version.
    assert "prod-130" not in deleted


def test_delete_only_targets_stopped_versions(tmp_path):
    # A SERVING (but idle) version must be eligible for STOP, never DELETE.
    result, _ = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=["prod-110", "prod-108", "prod-106"],
        traffic=["prod-110"],
        stopped=[],
    )
    assert result.returncode == 0, result.stderr
    assert _list_after("Stopping", result.stdout) == ["prod-106"]
    assert _list_after("Deleting", result.stdout) == []


# --- cleanup: fail-safe guard --------------------------------------------


def test_aborts_when_serving_versions_exist_but_none_serve_traffic(tmp_path):
    # If the traffic query returns nothing while versions are SERVING, we must
    # NOT stop anything (we cannot identify the live service).
    result, calls = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=["prod-104", "prod-102", "prod-100"],
        traffic=[],
        stopped=["prod-98"],
    )
    assert result.returncode != 0
    assert "refusing to stop" in result.stderr.lower()
    assert "Stopping" not in result.stdout
    assert calls.read_text() == ""


def test_no_serving_versions_is_not_an_error(tmp_path):
    # Nothing serving (all already stopped) is a valid state, not the guard case.
    result, _ = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=[],
        traffic=[],
        stopped=["prod-104", "prod-102"],
    )
    assert result.returncode == 0, result.stderr
    assert _list_after("Stopping", result.stdout) == []


# --- cleanup: robustness -------------------------------------------------


def test_handles_absence_of_staging_versions(tmp_path):
    # grep '^staging-' matches nothing; the script must not crash under set -e.
    result, _ = _run(
        CLEANUP_SCRIPT,
        tmp_path,
        serving=["prod-110"],
        traffic=["prod-110"],
        stopped=["prod-108", "prod-106", "20250101t000000"],
    )
    assert result.returncode == 0, result.stderr
    assert _list_after("Keeping stopped staging", result.stdout) == []
    assert _list_after("Deleting", result.stdout) == ["20250101t000000"]


# --- stop_app_engine_version.sh ------------------------------------------


def test_stop_script_requires_a_version(tmp_path):
    result, _ = _run(STOP_SCRIPT, tmp_path, extra_env={"APP_ENGINE_VERSION": ""})
    assert result.returncode != 0
    assert "APP_ENGINE_VERSION is required" in result.stderr


def test_stop_script_stops_the_named_version(tmp_path):
    result, calls = _run(
        STOP_SCRIPT,
        tmp_path,
        extra_env={"APP_ENGINE_VERSION": "staging-2405-abc1234", "DRY_RUN": "0"},
    )
    assert result.returncode == 0, result.stderr
    logged = calls.read_text()
    assert "STOP" in logged and "staging-2405-abc1234" in logged
