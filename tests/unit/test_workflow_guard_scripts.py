"""Tests for small workflow scripts.

The scripts are require_git_ref.sh and cleanup_cloud_run_images.sh.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REQUIRE_GIT_REF = ".github/scripts/require_git_ref.sh"
CLEANUP_IMAGES = ".github/scripts/cleanup_cloud_run_images.sh"


def _run(
    script: str, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", script, *args],
        cwd=REPO,
        env={"HOME": os.environ.get("HOME", ""), "PATH": os.environ["PATH"], **env},
        text=True,
        capture_output=True,
        check=False,
    )


def test_require_git_ref_passes_on_the_expected_ref() -> None:
    result = _run(
        REQUIRE_GIT_REF,
        {"GITHUB_REF": "refs/heads/master"},
        "refs/heads/master",
        "must run from master.",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_require_git_ref_fails_with_an_annotation_on_another_ref() -> None:
    result = _run(
        REQUIRE_GIT_REF,
        {"GITHUB_REF": "refs/heads/feature"},
        "refs/heads/master",
        "Cloud Run secret sync must run from master.",
    )

    assert result.returncode == 1
    assert result.stdout == "::error::Cloud Run secret sync must run from master.\n"


def _fake_gcloud(
    tmp_path: Path,
    rows: list[str],
    *,
    failing_refs: tuple[str, ...] = (),
    list_exit: int = 0,
) -> Path:
    """Return a bin dir whose fake gcloud lists ``rows`` and logs every other call.

    Deleting a ref in ``failing_refs`` prints an error and exits 1, and the
    listing exits with ``list_exit``.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    listing = tmp_path / "listing.txt"
    listing.write_text("".join(f"{row}\n" for row in rows))
    calls = tmp_path / "calls.log"
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1 $2 $3 $4" == "artifacts docker images list" ]]; then\n'
        f'  cat "{listing}"\n'
        f"  exit {list_exit}\n"
        "fi\n"
        f'echo "$*" >> "{calls}"\n'
        f"for failing_ref in {' '.join(failing_refs)}; do\n"
        '  if [[ "$5" == "${failing_ref}" ]]; then\n'
        '    echo "ERROR: PERMISSION_DENIED on $5" >&2\n'
        "    exit 1\n"
        "  fi\n"
        "done\n"
        'echo "Delete request issued for $5" >&2\n'
    )
    gcloud.chmod(0o755)
    return bin_dir


IMAGES = [
    "2026-01-01T00:00:00Z|repo/api|sha256:oldest",
    "2026-03-01T00:00:00Z|repo/api|sha256:newest",
    "2026-02-01T00:00:00Z|repo/api|sha256:middle",
]


def _cleanup(
    tmp_path: Path,
    rows: list[str],
    *,
    failing_refs: tuple[str, ...] = (),
    list_exit: int = 0,
    **env: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = _fake_gcloud(
        tmp_path, rows, failing_refs=failing_refs, list_exit=list_exit
    )
    result = _run(
        CLEANUP_IMAGES,
        {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **env},
    )
    calls_file = tmp_path / "calls.log"
    calls = calls_file.read_text().splitlines() if calls_file.exists() else []
    return result, calls


def test_cleanup_deletes_all_but_the_newest_images(tmp_path: Path) -> None:
    result, calls = _cleanup(tmp_path, IMAGES, KEEP="1")

    assert result.returncode == 0, result.stderr
    assert calls == [
        "artifacts docker images delete repo/api@sha256:middle --delete-tags --quiet",
        "artifacts docker images delete repo/api@sha256:oldest --delete-tags --quiet",
    ]
    assert "Deleted 2/2 image(s)." in result.stdout


def test_cleanup_dry_run_deletes_nothing(tmp_path: Path) -> None:
    result, calls = _cleanup(tmp_path, IMAGES, KEEP="1", DRY_RUN="1")

    assert result.returncode == 0, result.stderr
    assert calls == []
    assert "[dry-run] would delete repo/api@sha256:middle" in result.stdout
    assert "Deleted" not in result.stdout


def test_cleanup_keeps_everything_within_the_limit(tmp_path: Path) -> None:
    result, calls = _cleanup(tmp_path, IMAGES)

    assert result.returncode == 0, result.stderr
    assert calls == []
    assert "Deleting:  0" in result.stdout


def test_cleanup_reports_each_failed_deletion_and_fails(tmp_path: Path) -> None:
    result, calls = _cleanup(
        tmp_path, IMAGES, failing_refs=("repo/api@sha256:oldest",), KEEP="1"
    )

    assert result.returncode == 1
    assert len(calls) == 2
    assert "Failed to delete repo/api@sha256:oldest:\n" in result.stdout
    assert "  ERROR: PERMISSION_DENIED on repo/api@sha256:oldest\n" in result.stdout
    assert "Failed to delete repo/api@sha256:middle" not in result.stdout
    assert "Delete request issued" not in result.stdout
    assert "Deleted 1/2 image(s)." in result.stdout
    assert "::error::Failed to delete 1/2 image(s)" in result.stdout


def test_cleanup_fails_when_the_listing_fails(tmp_path: Path) -> None:
    result, calls = _cleanup(tmp_path, IMAGES, list_exit=1, KEEP="1")

    assert result.returncode == 1
    assert calls == []
    assert "::error::Could not list images in " in result.stdout
    assert "Images:" not in result.stdout
