"""Tests for small workflow scripts.

The scripts are require_git_ref.sh and cleanup_cloud_run_images.sh.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

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


# Stands in for Artifact Registry. Its state lives in FAKE_GCLOUD_DIR: the
# listing to print and its exit status, the refs whose deletion fails, and
# which child manifest each parent index references. Like Artifact Registry,
# it refuses to delete a child manifest until its parent has been deleted.
FAKE_GCLOUD = r"""#!/usr/bin/env bash
state="${FAKE_GCLOUD_DIR}"
if [[ "$1 $2 $3 $4" == "artifacts docker images list" ]]; then
  echo "$*" >> "${state}/list_calls.log"
  cat "${state}/listing.txt"
  exit "$(cat "${state}/list_exit.txt")"
fi
echo "$*" >> "${state}/calls.log"
ref="$5"
if grep -qxF "${ref}" "${state}/failing_refs.txt"; then
  echo "ERROR: PERMISSION_DENIED on ${ref}" >&2
  exit 1
fi
while read -r child parent; do
  if [[ "${ref}" == "${child}" ]] \
    && ! grep -qxF "${parent}" "${state}/deleted.log"; then
    echo "ERROR: (gcloud.artifacts.docker.images.delete) manifest is" \
      "referenced by parent manifests: failed precondition manifest has" \
      "referenced parents: policyengine-api/manifests/${parent#*@}" >&2
    exit 1
  fi
done < "${state}/parents.txt"
echo "${ref}" >> "${state}/deleted.log"
echo "Delete request issued for ${ref}" >&2
"""


def _manifest(uploaded: str, digest: str, tags: str = "") -> str:
    """Return one listing row, in the format the cleanup script asks gcloud for."""
    return f"{uploaded}|repo/api|sha256:{digest}|{tags}"


def _ref(digest: str) -> str:
    return f"repo/api@sha256:{digest}"


def _index_release(uploaded: str, name: str) -> list[str]:
    """Return the three manifests one release pushed from the ubuntu-26.04 runner.

    Docker's default provenance attestation made each push an image index
    (tagged) that references the image manifest and an attestation manifest
    (both untagged), all three listed with the same upload time. The
    children's digests sort above the index's, as in the failed release runs,
    so a newest-first sort that breaks ties by digest reaches them first.
    """
    return [
        _manifest(uploaded, f"{name}-index", name),
        _manifest(uploaded, f"{name}-image"),
        _manifest(uploaded, f"{name}-provenance"),
    ]


def _index_children(name: str) -> dict[str, str]:
    """Map each child manifest of ``_index_release(..., name)`` to its index."""
    return {
        _ref(f"{name}-image"): _ref(f"{name}-index"),
        _ref(f"{name}-provenance"): _ref(f"{name}-index"),
    }


# Releases built with one manifest each: on ubuntu-24.04, and with provenance
# attestations turned off.
SINGLE_MANIFEST_RELEASES = [
    _manifest("2026-01-01T00:00:00Z", "oldest", "release-1"),
    _manifest("2026-03-01T00:00:00Z", "newest", "release-3;latest"),
    _manifest("2026-02-01T00:00:00Z", "middle", "release-2"),
]


def _cleanup(
    tmp_path: Path,
    rows: list[str],
    *,
    failing_refs: tuple[str, ...] = (),
    parents: dict[str, str] | None = None,
    list_exit: int = 0,
    **env: str,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    """Run the cleanup script against the fake gcloud.

    Return the result, the gcloud deletion calls in order, and the arguments
    of each listing call.
    """
    state = tmp_path / "gcloud-state"
    state.mkdir()
    (state / "listing.txt").write_text("".join(f"{row}\n" for row in rows))
    (state / "list_exit.txt").write_text(f"{list_exit}\n")
    (state / "failing_refs.txt").write_text("".join(f"{ref}\n" for ref in failing_refs))
    (state / "parents.txt").write_text(
        "".join(f"{child} {parent}\n" for child, parent in (parents or {}).items())
    )
    (state / "deleted.log").write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(FAKE_GCLOUD)
    gcloud.chmod(0o755)
    result = _run(
        CLEANUP_IMAGES,
        {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GCLOUD_DIR": str(state),
            **env,
        },
    )

    def logged_lines(name: str) -> list[str]:
        log_file = state / name
        return log_file.read_text().splitlines() if log_file.exists() else []

    return result, logged_lines("calls.log"), logged_lines("list_calls.log")


def _delete_call(digest: str) -> str:
    return f"artifacts docker images delete {_ref(digest)} --delete-tags --quiet"


def test_cleanup_deletes_all_but_the_newest_releases(tmp_path: Path) -> None:
    result, calls, list_calls = _cleanup(tmp_path, SINGLE_MANIFEST_RELEASES, KEEP="1")

    assert result.returncode == 0, result.stderr
    assert calls == [_delete_call("middle"), _delete_call("oldest")]
    assert len(list_calls) == 1
    assert "--include-tags" in list_calls[0].split()
    assert "(createTime,package,version,tags)" in list_calls[0]
    assert "Deleted 2/2 manifest(s)." in result.stdout


def test_cleanup_counts_releases_not_manifests(tmp_path: Path) -> None:
    rows = (
        _index_release("2026-11-13T19:28:45Z", "newer")
        + _index_release("2026-11-12T22:05:18Z", "older")
        + _index_release("2026-11-11T18:22:24Z", "oldest")
    )
    parents = {
        **_index_children("newer"),
        **_index_children("older"),
        **_index_children("oldest"),
    }

    result, calls, _ = _cleanup(tmp_path, rows, parents=parents, KEEP="2")

    assert result.returncode == 0, result.stdout
    assert calls == [
        _delete_call("oldest-index"),
        _delete_call("oldest-provenance"),
        _delete_call("oldest-image"),
    ]
    assert "keeping newest 2" in result.stdout
    assert "Deleting:  3 (1 tagged, 2 untagged" in result.stdout
    assert "Deleted 3/3 manifest(s)." in result.stdout


def test_cleanup_deletes_untagged_manifests_older_than_every_kept_release(
    tmp_path: Path,
) -> None:
    rows = [
        _manifest("2026-11-13T19:28:45Z", "kept", "release-1"),
        _manifest("2026-11-12T22:05:18Z", "orphan-image"),
        _manifest("2026-11-12T22:05:18Z", "orphan-provenance"),
    ]

    result, calls, _ = _cleanup(tmp_path, rows)

    assert result.returncode == 0, result.stdout
    assert calls == [
        _delete_call("orphan-provenance"),
        _delete_call("orphan-image"),
    ]
    assert "Deleted 2/2 manifest(s)." in result.stdout


def test_cleanup_keeps_untagged_manifests_uploaded_after_the_oldest_kept_release(
    tmp_path: Path,
) -> None:
    rows = [
        _manifest("2026-11-13T19:28:45Z", "release-2", "release-2"),
        _manifest("2026-11-13T10:00:00Z", "retagged-index"),
        _manifest("2026-11-12T22:05:18Z", "release-1", "release-1"),
    ]

    result, calls, _ = _cleanup(tmp_path, rows, KEEP="2")

    assert result.returncode == 0, result.stdout
    assert calls == []
    assert "Deleting:  0" in result.stdout


def test_cleanup_skips_a_manifest_that_a_kept_image_still_references(
    tmp_path: Path,
) -> None:
    rows = [
        _manifest("2026-11-13T19:28:46Z", "newer-index", "release-2"),
        _manifest("2026-11-13T19:28:45Z", "newer-image"),
        _manifest("2026-11-13T19:28:45Z", "newer-provenance"),
        _manifest("2026-11-12T22:05:18Z", "older", "release-1"),
    ]

    result, calls, _ = _cleanup(
        tmp_path, rows, parents=_index_children("newer"), KEEP="1"
    )

    assert result.returncode == 0, result.stdout
    assert calls == [
        _delete_call("older"),
        _delete_call("newer-provenance"),
        _delete_call("newer-image"),
    ]
    assert (
        f"Kept {_ref('newer-provenance')}: another manifest still references it.\n"
    ) in result.stdout
    assert (
        "Deleted 1/3 manifest(s); kept 2 that another manifest still references."
    ) in result.stdout
    assert "::error::" not in result.stdout


def test_cleanup_deletes_nothing_without_a_tagged_release(tmp_path: Path) -> None:
    rows = [
        _manifest("2026-11-12T22:05:18Z", "untagged-image"),
        _manifest("2026-11-11T18:22:24Z", "untagged-provenance"),
    ]

    result, calls, _ = _cleanup(tmp_path, rows, KEEP="1")

    assert result.returncode == 0, result.stdout
    assert calls == []
    assert "::warning::No tagged image in " in result.stdout


def test_cleanup_dry_run_deletes_nothing(tmp_path: Path) -> None:
    result, calls, _ = _cleanup(
        tmp_path, SINGLE_MANIFEST_RELEASES, KEEP="1", DRY_RUN="1"
    )

    assert result.returncode == 0, result.stderr
    assert calls == []
    assert f"[dry-run] would delete {_ref('middle')}\n" in result.stdout
    assert f"[dry-run] would delete {_ref('oldest')}\n" in result.stdout
    assert "Deleted" not in result.stdout


def test_cleanup_keeps_everything_within_the_limit(tmp_path: Path) -> None:
    result, calls, _ = _cleanup(tmp_path, SINGLE_MANIFEST_RELEASES)

    assert result.returncode == 0, result.stderr
    assert calls == []
    assert "Deleting:  0" in result.stdout


def test_cleanup_reports_each_failed_deletion_and_fails(tmp_path: Path) -> None:
    result, calls, _ = _cleanup(
        tmp_path,
        SINGLE_MANIFEST_RELEASES,
        failing_refs=(_ref("oldest"),),
        KEEP="1",
    )

    assert result.returncode == 1
    assert calls == [_delete_call("middle"), _delete_call("oldest")]
    assert f"Failed to delete {_ref('oldest')}:\n" in result.stdout
    assert f"  ERROR: PERMISSION_DENIED on {_ref('oldest')}\n" in result.stdout
    assert f"Failed to delete {_ref('middle')}" not in result.stdout
    assert "Delete request issued" not in result.stdout
    assert "Deleted 1/2 manifest(s)." in result.stdout
    assert "::error::Failed to delete 1/2 manifest(s)" in result.stdout


def test_cleanup_fails_when_a_parent_it_must_delete_cannot_be_deleted(
    tmp_path: Path,
) -> None:
    rows = _index_release("2026-11-13T19:28:45Z", "newer") + _index_release(
        "2026-11-12T22:05:18Z", "older"
    )
    parents = {**_index_children("newer"), **_index_children("older")}

    result, calls, _ = _cleanup(
        tmp_path,
        rows,
        parents=parents,
        failing_refs=(_ref("older-index"),),
        KEEP="1",
    )

    assert result.returncode == 1
    assert calls == [
        _delete_call("older-index"),
        _delete_call("older-provenance"),
        _delete_call("older-image"),
    ]
    assert (
        "Deleted 0/3 manifest(s); kept 2 that another manifest still references."
        in (result.stdout)
    )
    assert "::error::Failed to delete 1/3 manifest(s)" in result.stdout


def test_cleanup_fails_when_the_listing_fails(tmp_path: Path) -> None:
    result, calls, _ = _cleanup(
        tmp_path, SINGLE_MANIFEST_RELEASES, list_exit=1, KEEP="1"
    )

    assert result.returncode == 1
    assert calls == []
    assert "::error::Could not list images in " in result.stdout
    assert "Manifests:" not in result.stdout


@pytest.mark.parametrize("keep", ["0", "-1", "abc", "1.5"])
def test_cleanup_rejects_a_keep_below_one_release(tmp_path: Path, keep: str) -> None:
    result, calls, list_calls = _cleanup(tmp_path, SINGLE_MANIFEST_RELEASES, KEEP=keep)

    assert result.returncode == 1
    assert calls == []
    assert list_calls == []
    assert (
        f"::error::KEEP must be a whole number of releases, 1 or more; got '{keep}'."
    ) in result.stdout
