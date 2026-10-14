#!/usr/bin/env bash

# Fail unless the workflow runs from the expected git ref.
#
# Usage: require_git_ref.sh <expected-ref> <error-message>
# Reads GITHUB_REF, which GitHub Actions sets for every job.

set -euo pipefail

expected_ref="${1:?expected git ref is required}"
message="${2:?error message is required}"

if [[ "${GITHUB_REF:-}" != "${expected_ref}" ]]; then
  echo "::error::${message}"
  exit 1
fi
