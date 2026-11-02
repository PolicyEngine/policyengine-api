#!/usr/bin/env bash

# Decide whether this release run may skip the checks its merge run passed,
# for push.yml's check-release-commit job (.github/release_commit.py explains
# the decision).
#
# It gathers what release_commit.py reads: from git, the release commit's
# changes and the parent's copies of pyproject.toml and uv.lock; from the
# GitHub API, the parent's Push runs and the jobs of each. Then
# release_commit.py check writes merge_run_checks_passed (true or false) and
# merge_run_url to GITHUB_OUTPUT. When this script cannot gather something, it
# writes merge_run_checks_passed=false, so the run runs the checks itself, and
# exits 0.
#
# Run from the repository root, in a checkout of the release commit and its
# parent (actions/checkout with fetch-depth: 2).
#
# Environment:
#   GH_TOKEN           a token that can read this repository's Actions runs
#   GITHUB_REPOSITORY  the repository, as owner/name
#   GITHUB_OUTPUT      the step's output file
#   PYTHON             the Python 3.11+ interpreter (default: python3)

set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required}"
repository="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
output_file="${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
python_bin="${PYTHON:-python3}"
release_commit_module="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/release_commit.py"
gathered="$(mktemp -d)"
trap 'rm -rf "${gathered}"' EXIT

run_the_checks() {
  echo "::notice::$1 This run runs the checks itself."
  {
    echo "merge_run_checks_passed=false"
    echo "merge_run_url="
  } >>"${output_file}"
  exit 0
}

read -r -a commit_and_parents <<<"$(git rev-list --parents -n 1 HEAD)"
if ((${#commit_and_parents[@]} != 2)); then
  run_the_checks "The release commit must have exactly one parent."
fi
parent="${commit_and_parents[1]}"

if ! git diff --raw --no-renames --no-abbrev -z "${parent}" HEAD >"${gathered}/changes"; then
  run_the_checks "Could not compare the release commit with its parent ${parent}."
fi
for versioned_file in pyproject.toml uv.lock; do
  if ! git show "${parent}:${versioned_file}" >"${gathered}/parent-${versioned_file}"; then
    run_the_checks "Could not read ${versioned_file} at the parent ${parent}."
  fi
done

runs_request="repos/${repository}/actions/workflows/push.yml/runs?head_sha=${parent}&event=push&per_page=100"
if ! gh api "${runs_request}" >"${gathered}/runs.json"; then
  run_the_checks "Could not list the Push runs of the parent ${parent}."
fi
if ! run_ids="$(jq -r '.workflow_runs[].id' "${gathered}/runs.json")"; then
  run_the_checks "Could not read the Push runs of the parent ${parent}."
fi
for run_id in ${run_ids}; do
  if ! gh api "repos/${repository}/actions/runs/${run_id}/jobs?per_page=100" >"${gathered}/jobs-${run_id}.json"; then
    run_the_checks "Could not list the jobs of Push run ${run_id}."
  fi
done

"${python_bin}" "${release_commit_module}" check --gathered "${gathered}" --output "${output_file}"
