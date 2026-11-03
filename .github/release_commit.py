"""Decide whether a release run may skip the checks its merge run passed.

After a merge to master, push.yml's merge run runs the checks in
``MERGE_RUN_CHECKS`` (lint, the quality guards, the Alembic v1 and v2 checks
and the cross-database integration tests), and its versioning job then pushes
the release commit, "Update PolicyEngine API", whose own run deploys. That
release run skips those checks only when both of these hold:

1. The release commit changes nothing but release files: the version in
   pyproject.toml's [project] table, the project's own version entry in
   uv.lock, CHANGELOG.md, and fragments it removes from the fragment
   directory (changelog.d/). Every check then reads the same code as on the
   merge commit.
2. The release commit's parent, the merge commit, has a Push run in which
   every check in ``MERGE_RUN_CHECKS`` passed.

Otherwise the release run runs the checks itself, as it did before, and
publishes the tag only when the ones in ``RELEASE_RUN_REQUIRED_CHECKS`` pass.

.github/scripts/check_release_commit.sh gathers what the decision reads (the
release commit's changes, the parent's copies of pyproject.toml and uv.lock,
and the parent's Push runs and their jobs from the GitHub API) and runs the
``check`` command.

Commands, run from the repository root of a checkout of the release commit:

  check           read the files check_release_commit.sh gathered, print the
                  reasons the checks cannot be skipped, and write
                  ``merge_run_checks_passed=true`` or ``false`` and the merge
                  run's URL to ``--output``
  require-checks  for publish-git-tag: read its ``toJSON(needs)`` from the
                  JOB_RESULTS environment variable, and exit 1 unless either
                  the release commit check let this run skip the checks and
                  none of them failed, or every check in
                  ``RELEASE_RUN_REQUIRED_CHECKS`` passed in this run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from changelog_fragments import KEEP_FILE, ConfigurationError, FragmentDefinition

# The checks a merge run must have passed, by push.yml job id, with the job's
# name. A check that calls a reusable workflow reports each of that
# workflow's jobs as "<name> / <job name>".
MERGE_RUN_CHECKS = {
    "lint": "Lint",
    "quality-guards": "Quality guards",
    "alembic-v1-check": "Alembic v1 qualification",
    "alembic-v2-check": "Alembic v2 qualification",
    "v2-integration-check": "Cross-database integration tests",
}
# The checks a release run that runs them itself requires before it publishes
# the tag: all of the above but the quality guards, which no deploy job
# required before either.
RELEASE_RUN_REQUIRED_CHECKS = (
    "lint",
    "alembic-v1-check",
    "alembic-v2-check",
    "v2-integration-check",
)
RELEASE_COMMIT_CHECK_JOB = "check-release-commit"
CHECKS_PASSED_OUTPUT = "merge_run_checks_passed"
MERGE_RUN_URL_OUTPUT = "merge_run_url"
PYPROJECT_FILE = "pyproject.toml"
LOCK_FILE = "uv.lock"
CHANGELOG_FILE = "CHANGELOG.md"
REGULAR_FILE_MODE = "100644"
# git diff --raw statuses.
MODIFIED = "M"
DELETED = "D"
# A file's own entry in git diff --raw: ":<old mode> <new mode> <old object>
# <new object> <status>", then the path.
RAW_DIFF_ENTRY = re.compile(
    r":(?P<old_mode>\d{6}) (?P<new_mode>\d{6}) [0-9a-f]+ [0-9a-f]+ "
    r"(?P<status>[A-Z])\d*"
)
VERSION_ENTRY = re.compile(r'^version\s*=\s*"[^"\n]*"\s*$')
NAME_ENTRY = re.compile(r'^name\s*=\s*"(?P<name>[^"\n]*)"\s*$')
PACKAGE_HEADER = "[[package]]"
PROJECT_HEADER = "[project]"
SUCCESS = "success"
SKIPPED = "skipped"


@dataclass(frozen=True)
class FileChange:
    """One path the release commit changes, from git diff --raw."""

    path: str
    status: str
    old_mode: str
    new_mode: str


@dataclass(frozen=True)
class ReleaseFiles:
    """The parent's and the release commit's copies of the versioned files."""

    parent_pyproject: str
    release_pyproject: str
    parent_lock: str
    release_lock: str


def parse_raw_diff(raw_diff: str) -> list[FileChange]:
    """Return the changes in ``git diff --raw --no-renames -z`` output."""
    fields = raw_diff.split("\0")
    if fields and not fields[-1]:
        fields.pop()
    if len(fields) % 2:
        msg = "git diff --raw -z output must alternate entries and paths"
        raise ValueError(msg)
    changes = []
    for entry, path in zip(fields[0::2], fields[1::2], strict=True):
        match = RAW_DIFF_ENTRY.fullmatch(entry)
        if match is None:
            msg = f"unexpected git diff --raw entry: {entry!r}"
            raise ValueError(msg)
        changes.append(
            FileChange(
                path=path,
                status=match["status"],
                old_mode=match["old_mode"],
                new_mode=match["new_mode"],
            )
        )
    return changes


def normalized_package_name(name: str) -> str:
    """Return ``name`` as uv.lock and PEP 503 write it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def project_version_index(pyproject_text: str) -> int | None:
    """Return the index of the version line in pyproject.toml's [project] table."""
    in_project_table = False
    for index, line in enumerate(pyproject_text.splitlines()):
        if line.startswith("["):
            in_project_table = line.strip() == PROJECT_HEADER
        elif in_project_table and VERSION_ENTRY.match(line):
            return index
    return None


def locked_project_version_index(lock_text: str, project_name: str) -> int | None:
    """Return the index of the version line in uv.lock's entry for ``project_name``.

    uv.lock writes each package as a ``[[package]]`` table whose own keys,
    ``name`` and ``version`` first, come before the next table header.
    """
    lines = lock_text.splitlines()
    for header_index, header in enumerate(lines):
        if header.strip() != PACKAGE_HEADER:
            continue
        package_name = None
        version_index = None
        for index in range(header_index + 1, len(lines)):
            line = lines[index]
            if line.startswith("["):
                break
            name_match = NAME_ENTRY.match(line)
            if name_match is not None:
                package_name = normalized_package_name(name_match["name"])
            elif version_index is None and VERSION_ENTRY.match(line):
                version_index = index
        if package_name == project_name:
            return version_index
    return None


def changes_only_line(
    parent_text: str,
    release_text: str,
    parent_index: int | None,
    release_index: int | None,
) -> bool:
    """Whether the two texts are the same except for the given line."""
    if parent_index is None or release_index is None or parent_index != release_index:
        return False
    parent_lines = parent_text.splitlines(keepends=True)
    release_lines = release_text.splitlines(keepends=True)
    return (
        len(parent_lines) == len(release_lines)
        and parent_lines[:parent_index] == release_lines[:release_index]
        and parent_lines[parent_index + 1 :] == release_lines[release_index + 1 :]
    )


def project_name(pyproject_text: str) -> str:
    """Return the normalized [project] name in pyproject.toml."""
    return normalized_package_name(tomllib.loads(pyproject_text)["project"]["name"])


def _is_modified_regular_file(change: FileChange) -> bool:
    return (
        change.status == MODIFIED
        and change.old_mode == REGULAR_FILE_MODE
        and change.new_mode == REGULAR_FILE_MODE
    )


def release_change_problems(
    changes: list[FileChange],
    files: ReleaseFiles,
    fragment_directory: str,
) -> list[str]:
    """Return why ``changes`` hold more than a release commit may, or nothing."""
    problems = []
    for change in changes:
        path = PurePosixPath(change.path)
        if change.path == CHANGELOG_FILE:
            if not _is_modified_regular_file(change):
                problems.append(f"{CHANGELOG_FILE} is not only edited")
        elif change.path == PYPROJECT_FILE:
            if not _is_modified_regular_file(change) or not changes_only_line(
                files.parent_pyproject,
                files.release_pyproject,
                project_version_index(files.parent_pyproject),
                project_version_index(files.release_pyproject),
            ):
                problems.append(
                    f"{PYPROJECT_FILE} changes more than the [project] version"
                )
        elif change.path == LOCK_FILE:
            name = project_name(files.release_pyproject)
            if not _is_modified_regular_file(change) or not changes_only_line(
                files.parent_lock,
                files.release_lock,
                locked_project_version_index(files.parent_lock, name),
                locked_project_version_index(files.release_lock, name),
            ):
                problems.append(f"{LOCK_FILE} changes more than {name}'s version")
        elif str(path.parent) == fragment_directory and path.name != KEEP_FILE:
            if change.status != DELETED:
                problems.append(
                    f"{change.path} is a fragment the release commit does not remove"
                )
        else:
            problems.append(f"{change.path} is not a release file")
    return problems


def _check_jobs(jobs: list[dict], check_name: str) -> list[dict]:
    """Return the jobs that report the push.yml check named ``check_name``."""
    return [
        job
        for job in jobs
        if job.get("name") == check_name
        or str(job.get("name", "")).startswith(f"{check_name} / ")
    ]


def run_check_problems(jobs: list[dict]) -> list[str]:
    """Return the merge-run checks that did not pass in a run with ``jobs``."""
    problems = []
    for check_name in MERGE_RUN_CHECKS.values():
        check_jobs = _check_jobs(jobs, check_name)
        if not check_jobs:
            problems.append(f"{check_name} did not run")
            continue
        problems.extend(
            f"{job.get('name')} ended {job.get('status')}, {job.get('conclusion')}"
            for job in check_jobs
            if job.get("status") != "completed" or job.get("conclusion") != SUCCESS
        )
    return problems


def passing_merge_run(
    runs: list[dict], jobs_by_run: dict[int, list[dict]]
) -> tuple[dict | None, list[str]]:
    """Return a run in which every merge-run check passed, or why there is none."""
    if not runs:
        return None, ["the parent commit has no Push run"]
    problems = []
    for run in runs:
        run_problems = run_check_problems(jobs_by_run.get(run["id"], []))
        if not run_problems:
            return run, []
        problems.extend(
            f"Push run {run.get('html_url', run['id'])}: {run_problem}"
            for run_problem in run_problems
        )
    return None, problems


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_outputs(
    output_path: Path, *, checks_passed: bool, merge_run_url: str
) -> None:
    with output_path.open("a", encoding="utf-8") as output:
        output.write(f"{CHECKS_PASSED_OUTPUT}={'true' if checks_passed else 'false'}\n")
        output.write(f"{MERGE_RUN_URL_OUTPUT}={merge_run_url}\n")


def check(arguments: argparse.Namespace) -> int:
    """Run the ``check`` command."""
    gathered = Path(arguments.gathered)
    problems = []
    try:
        fragment_directory = FragmentDefinition.load(Path.cwd()).directory
    except ConfigurationError as error:
        problems.append(str(error))
        fragment_directory = ""
    files = ReleaseFiles(
        parent_pyproject=_read_text(gathered / "parent-pyproject.toml"),
        release_pyproject=_read_text(Path(PYPROJECT_FILE)),
        parent_lock=_read_text(gathered / "parent-uv.lock"),
        release_lock=_read_text(Path(LOCK_FILE)),
    )
    changes = parse_raw_diff(_read_text(gathered / "changes"))
    if fragment_directory:
        problems.extend(release_change_problems(changes, files, fragment_directory))
    runs = json.loads(_read_text(gathered / "runs.json") or "{}").get(
        "workflow_runs", []
    )
    jobs_by_run = {
        run["id"]: json.loads(
            _read_text(gathered / f"jobs-{run['id']}.json") or "{}"
        ).get("jobs", [])
        for run in runs
    }
    merge_run, run_problems = passing_merge_run(runs, jobs_by_run)
    problems.extend(run_problems)
    for problem in problems:
        print(f"::notice::{problem}")
    checks_passed = not problems
    merge_run_url = merge_run.get("html_url", "") if merge_run else ""
    if checks_passed:
        print(
            "The release commit changes only release files, and the merge run "
            f"{merge_run_url} passed every check on the same code: this run skips "
            f"{', '.join(MERGE_RUN_CHECKS.values())}."
        )
    else:
        print("This run runs the checks itself.")
    _write_outputs(
        Path(arguments.output), checks_passed=checks_passed, merge_run_url=merge_run_url
    )
    return 0


def release_check_problems(job_results: dict) -> list[str]:
    """Return why publish-git-tag may not proceed, from its ``toJSON(needs)``."""
    release_commit_check = job_results.get(RELEASE_COMMIT_CHECK_JOB, {})
    skipped_by_design = (
        release_commit_check.get("result") == SUCCESS
        and release_commit_check.get("outputs", {}).get(CHECKS_PASSED_OUTPUT) == "true"
    )
    allowed_results = {SUCCESS, SKIPPED} if skipped_by_design else {SUCCESS}
    problems = []
    for job_id in RELEASE_RUN_REQUIRED_CHECKS:
        if job_id not in job_results:
            problems.append(f"publish-git-tag does not need {job_id}")
            continue
        result = job_results[job_id].get("result")
        if result not in allowed_results:
            problems.append(f"{job_id} ended {result}")
    return problems


def require_checks(_arguments: argparse.Namespace) -> int:
    """Run the ``require-checks`` command."""
    job_results = json.loads(os.environ.get("JOB_RESULTS", "{}"))
    problems = release_check_problems(job_results)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    release_commit_check = job_results[RELEASE_COMMIT_CHECK_JOB]
    merge_run_url = release_commit_check.get("outputs", {}).get(MERGE_RUN_URL_OUTPUT)
    if merge_run_url:
        print(f"This run skipped the checks the merge run {merge_run_url} passed.")
    else:
        print("This run's checks passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run one command."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check")
    check_parser.add_argument("--gathered", required=True)
    check_parser.add_argument("--output", required=True)
    check_parser.set_defaults(handler=check)
    require_parser = commands.add_parser("require-checks")
    require_parser.set_defaults(handler=require_checks)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
