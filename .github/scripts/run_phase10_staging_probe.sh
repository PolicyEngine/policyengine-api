#!/usr/bin/env bash

set -euo pipefail

: "${POLICYENGINE_DB_READONLY_PASSWORD_SECRET:?POLICYENGINE_DB_READONLY_PASSWORD_SECRET is required}"

case "${1:-}" in
  activation)
    test_name="test_live_phase10_activation_failure_and_retry"
    ;;
  rollback)
    test_name="test_live_phase10_cloud_sql_only_rollback"
    ;;
  *)
    echo "Usage: $0 {activation|rollback}" >&2
    exit 1
    ;;
esac

readonly_password="$(
  gcloud secrets versions access latest \
    --secret "${POLICYENGINE_DB_READONLY_PASSWORD_SECRET}" \
    --project policyengine-api
)"
if [[ -z "${readonly_password}" ]]; then
  echo "The staging Cloud SQL read-only password must not be empty." >&2
  exit 1
fi

if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  printf '::add-mask::%s\n' "${readonly_password}"
fi
POLICYENGINE_DB_READONLY_PASSWORD="${readonly_password}" \
  python -m pytest \
  "tests/integration/test_live_phase10_staging.py::${test_name}" \
  -v
