#!/usr/bin/env bash

set -euo pipefail

: "${POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET:?POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET is required}"
: "${HOUSEHOLD_MIRROR_OPERATOR_IDENTITY:?HOUSEHOLD_MIRROR_OPERATOR_IDENTITY is required}"
: "${ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY:?ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY is required}"

bash .github/scripts/validate_database_environment.sh cloud-sql
bash .github/scripts/validate_database_environment.sh supabase

if [[ "${HOUSEHOLD_MIRROR_OPERATOR_IDENTITY}" != \
  "${ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY}" ]]; then
  echo "The authenticated service-account declaration is not authorized for household event processing." >&2
  exit 1
fi

migration_password="$(
  gcloud secrets versions access latest \
    --secret "${POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET}" \
    --project policyengine-api
)"
if [[ -z "${migration_password}" ]]; then
  echo "The Cloud SQL migration password must not be empty." >&2
  exit 1
fi
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  printf '::add-mask::%s\n' "${migration_password}"
fi

POLICYENGINE_DB_PROXY_PORT="3307" \
  POLICYENGINE_DB_PASSWORD="${migration_password}" \
  python scripts/process_v1_household_mirror_event.py "$@"
