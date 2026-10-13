#!/usr/bin/env bash

# Gate behind the "CI complete" check in pr.yml.
#
# In a stack of pull requests, only the lowest unmerged one runs the full
# workflow; the jobs of the others are skipped to save runners. A skipped job
# counts as passing for a required check, so this gate fails on those pull
# requests instead. On every other pull request it passes only when every job
# it needs passed.
#
# Environment:
#   JOB_RESULTS            toJSON(needs) for the gate job
#   PULL_REQUEST_BASE_REF  github.event.pull_request.base.ref
#   STACK_BASE_REF         github.event.pull_request.stack.base.ref, empty when
#                          the pull request isn't in a stack

set -euo pipefail

job_results="${JOB_RESULTS:?JOB_RESULTS is required}"
pull_request_base_ref="${PULL_REQUEST_BASE_REF:?PULL_REQUEST_BASE_REF is required}"
stack_base_ref="${STACK_BASE_REF:-}"

if [[ -n "${stack_base_ref}" && "${stack_base_ref}" != "${pull_request_base_ref}" ]]; then
  echo "::error::Full CI runs only on the lowest unmerged pull request in a stack. This one targets ${pull_request_base_ref}; it runs once the pull request below it merges and this one is rebased onto ${stack_base_ref}."
  exit 1
fi

unsuccessful_jobs="$(
  jq -r 'to_entries[] | select(.value.result != "success") | "\(.key): \(.value.result)"' <<<"${job_results}"
)"

if [[ -n "${unsuccessful_jobs}" ]]; then
  while IFS= read -r unsuccessful_job; do
    echo "::error::Job did not pass: ${unsuccessful_job}"
  done <<<"${unsuccessful_jobs}"
  exit 1
fi

echo "Every job passed."
