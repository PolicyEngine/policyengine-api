"""The release run's tag script tags the release commit with its version."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from tests.unit.cloud_run_deploy_support import REPO

if TYPE_CHECKING:
    from pathlib import Path

SCRIPT = REPO / ".github/scripts/publish_git_tag.sh"
RELEASE_VERSION = "1.2.3"
PYPROJECT = f'[project]\nname = "policyengine-api"\nversion = "{RELEASE_VERSION}"\n'
GIT_IDENTITY = (
    "-c",
    "user.name=Release test",
    "-c",
    "user.email=release-test@example.test",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "tag.gpgsign=false",
)


@dataclass(frozen=True)
class ReleaseCheckout:
    """A clone at a release commit, with a bare repository as its origin."""

    checkout: Path
    origin: Path
    env: dict[str, str]

    def git(self, *arguments: str) -> str:
        """Run git in the clone and return its output."""
        return _git(self.checkout, self.env, *arguments)

    def commit(self, pyproject: str, message: str) -> str:
        """Commit ``pyproject`` as pyproject.toml and return the new commit."""
        (self.checkout / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        self.git("add", "pyproject.toml")
        self.git(*GIT_IDENTITY, "commit", "--quiet", "--message", message)
        return self.git("rev-parse", "HEAD")

    def origin_tags(self) -> dict[str, str]:
        """Return each tag on the origin with the commit it names."""
        listing = self.git("ls-remote", "--tags", "origin")
        tags: dict[str, str] = {}
        for listed in listing.splitlines():
            commit, reference = listed.split("\t")
            tag_name = reference.removeprefix("refs/tags/").removesuffix("^{}")
            tags[tag_name] = commit
        return tags

    def publish(self) -> subprocess.CompletedProcess[str]:
        """Run the tag script in the clone."""
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=self.checkout,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )


def _git(directory: Path, env: dict[str, str], *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def _release_checkout(tmp_path: Path, pyproject: str = PYPROJECT) -> ReleaseCheckout:
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    origin = tmp_path / "origin.git"
    checkout = tmp_path / "checkout"
    _git(tmp_path, env, "init", "--quiet", "--bare", str(origin))
    _git(tmp_path, env, "init", "--quiet", str(checkout))
    release = ReleaseCheckout(checkout=checkout, origin=origin, env=env)
    release.commit(pyproject, "Update PolicyEngine API")
    release.git("remote", "add", "origin", str(origin))
    release.git("push", "--quiet", "origin", "HEAD:refs/heads/master")
    return release


def test_tags_the_release_commit_with_its_pyproject_version(tmp_path):
    release = _release_checkout(tmp_path)

    result = release.publish()

    assert result.returncode == 0, result.stderr
    assert release.origin_tags() == {RELEASE_VERSION: release.git("rev-parse", "HEAD")}


def test_pushes_only_the_release_tag(tmp_path):
    release = _release_checkout(tmp_path)
    release.git("tag", "local-only")

    result = release.publish()

    assert result.returncode == 0, result.stderr
    assert set(release.origin_tags()) == {RELEASE_VERSION}


@pytest.mark.parametrize(
    "pyproject",
    [
        '[project]\nname = "policyengine-api"\n',
        '[project]\nname = "policyengine-api"\nversion = "latest"\n',
    ],
    ids=["no-version", "not-a-release-version"],
)
def test_fails_without_a_release_version(tmp_path, pyproject):
    release = _release_checkout(tmp_path, pyproject)

    result = release.publish()

    assert result.returncode != 0
    assert "version" in result.stderr
    assert release.origin_tags() == {}


def test_fails_when_the_tag_names_another_commit(tmp_path):
    release = _release_checkout(tmp_path)
    earlier_commit = release.git("rev-parse", "HEAD")
    release.git(
        "push", "--quiet", "origin", f"{earlier_commit}:refs/tags/{RELEASE_VERSION}"
    )
    release_commit = release.commit(
        PYPROJECT + "# a later release commit\n", "Update PolicyEngine API"
    )

    result = release.publish()

    assert result.returncode != 0
    assert earlier_commit in result.stderr
    assert release_commit in result.stderr
    assert release.origin_tags() == {RELEASE_VERSION: earlier_commit}


@pytest.mark.parametrize("annotated", [False, True], ids=["lightweight", "annotated"])
def test_accepts_a_tag_that_already_names_the_release_commit(tmp_path, annotated):
    release = _release_checkout(tmp_path)
    release_commit = release.git("rev-parse", "HEAD")
    if annotated:
        release.git(
            *GIT_IDENTITY, "tag", "--annotate", "--message", "Release", "existing"
        )
        release.git(
            "push",
            "--quiet",
            "origin",
            f"refs/tags/existing:refs/tags/{RELEASE_VERSION}",
        )
        release.git("tag", "--delete", "existing")
    else:
        release.git("push", "--quiet", "origin", f"HEAD:refs/tags/{RELEASE_VERSION}")
    tags_before = release.git("ls-remote", "--tags", "origin")

    result = release.publish()

    assert result.returncode == 0, result.stderr
    assert release.git("ls-remote", "--tags", "origin") == tags_before
    assert release.origin_tags()[RELEASE_VERSION] == release_commit
