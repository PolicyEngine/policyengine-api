#!/usr/bin/env bash

# Decide whether the full-catalog-integration job in
# .github/workflows/v2-integration-check.yml runs its tests.
#
# Those tests load the complete installed PolicyEngine.py catalog (about 1.2
# million parameter values) and take 5 to 25 minutes, depending on the runner.
# Their outcome can change only when one of the paths in full_catalog_paths
# below changes, so a pull request or a push runs them only when it touches
# one, and a scheduled or manual run always runs them. Either way the job
# runs, and only its later steps are skipped: "CI complete" fails on a skipped
# job, and a release run may skip the cross-database integration tests only
# when every job of its merge run's check succeeded (.github/release_commit.py).
#
# The comparison starts at the merge base of BASE_SHA and HEAD. For a pull
# request, GitHub checks out its test merge commit, whose first parent is
# BASE_SHA, so the comparison holds exactly what merging adds; for a push, it
# holds what the push added. When BASE_SHA is empty, all zeros (a new branch)
# or not in the clone's history (a force push), the tests run.
#
# Run from the repository root, in a clone with the base commit's history
# (actions/checkout with fetch-depth: 0).
#
# Environment:
#   EVENT_NAME     github.event_name: pull_request, push, schedule or
#                  workflow_dispatch
#   BASE_SHA       the commit to compare with: github.event.pull_request.base.sha
#                  for a pull request, github.event.before for a push
#   GITHUB_OUTPUT  the step output file; receives run_full_catalog_tests=true
#                  or run_full_catalog_tests=false

set -euo pipefail

event_name="${EVENT_NAME:?EVENT_NAME is required: github.event_name}"
output_file="${GITHUB_OUTPUT:?GITHUB_OUTPUT is required: the step output file}"
base_revision="${BASE_SHA:-}"

# What the full-catalog tests' outcome depends on: the locked PolicyEngine.py
# and country model packages, the catalog code and the models of the tables it
# publishes to, the v2 schema, the tests and their shared catalog, and how CI
# runs them. Each entry is a glob matched against the whole path.
full_catalog_paths=(
  "uv.lock"
  "pyproject.toml"
  "policyengine_api/data/v2/catalog/*"
  "policyengine_api/data/v2/models/metadata.py"
  "migrations/v2/*"
  "alembic-v2.ini"
  "tests/fixtures/installed_catalog.py"
  "tests/integration/test_v2_catalog_installed.py"
  "tests/integration/test_v2_catalog_publication_qualification.py"
  ".github/workflows/v2-integration-check.yml"
  ".github/scripts/decide_full_catalog_tests.sh"
)

decide() {
  echo "run_full_catalog_tests=$1" >>"${output_file}"
}

touches_full_catalog() {
  local changed_path="$1"
  local pattern
  for pattern in "${full_catalog_paths[@]}"; do
    # The pattern is unquoted so that it matches as a glob.
    # shellcheck disable=SC2053
    if [[ "${changed_path}" == ${pattern} ]]; then
      return 0
    fi
  done
  return 1
}

if [[ "${event_name}" != "pull_request" && "${event_name}" != "push" ]]; then
  echo "A ${event_name} run runs the full-catalog tests whatever changed."
  decide true
  exit 0
fi

if [[ -z "${base_revision}" || "${base_revision}" =~ ^0+$ ]]; then
  echo "::notice::There is no commit to compare with, so the full-catalog tests run."
  decide true
  exit 0
fi

if ! base_commit="$(git merge-base "${base_revision}" HEAD 2>/dev/null)"; then
  echo "::notice::${base_revision} is not in this clone's history, so the full-catalog tests run."
  decide true
  exit 0
fi

# --no-renames lists a moved file under its old path as well as its new one.
changed_paths="$(git -c core.quotePath=false diff --name-only --no-renames "${base_commit}" HEAD)"
matching_paths=()
while IFS= read -r changed_path; do
  if [[ -n "${changed_path}" ]] && touches_full_catalog "${changed_path}"; then
    matching_paths+=("${changed_path}")
  fi
done <<<"${changed_paths}"

if ((${#matching_paths[@]} == 0)); then
  echo "The change touches none of the paths the full-catalog tests depend on, so they are skipped. A nightly run and every change to those paths still run them."
  decide false
  exit 0
fi

echo "The change touches paths the full-catalog tests depend on, so they run:"
printf '  %s\n' "${matching_paths[@]}"
decide true
