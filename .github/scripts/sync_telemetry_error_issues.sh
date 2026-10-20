#!/usr/bin/env bash
# Run the daily telemetry error report with the settings the workflow passes
# in the environment. DRY_RUN=true adds --dry-run; a non-empty REPORT_DATE
# (YYYY-MM-DD, an Eastern calendar day) replaces the default previous day.
set -euo pipefail

: "${GOOGLE_OAUTH_ACCESS_TOKEN:?GOOGLE_OAUTH_ACCESS_TOKEN is required}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${TELEMETRY_ERROR_FINGERPRINT_KEY:?TELEMETRY_ERROR_FINGERPRINT_KEY is required}"
: "${OBSERVABILITY_PROJECT_ID:?OBSERVABILITY_PROJECT_ID is required}"

# Hide both values in the job log even if a later command prints them.
echo "::add-mask::${GOOGLE_OAUTH_ACCESS_TOKEN}"
echo "::add-mask::${TELEMETRY_ERROR_FINGERPRINT_KEY}"

arguments=(--project-id "${OBSERVABILITY_PROJECT_ID}")
if [[ "${DRY_RUN:-false}" == "true" ]]; then
  arguments+=(--dry-run)
fi
if [[ -n "${REPORT_DATE:-}" ]]; then
  arguments+=(--report-date "${REPORT_DATE}")
fi

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${script_directory}/sync_telemetry_error_issues.py" "${arguments[@]}"
