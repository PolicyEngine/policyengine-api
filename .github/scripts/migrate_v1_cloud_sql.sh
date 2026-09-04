#!/usr/bin/env bash

set -euo pipefail

: "${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME:?POLICYENGINE_DB_INSTANCE_CONNECTION_NAME is required}"
: "${POLICYENGINE_DB_READONLY_PASSWORD_SECRET:?POLICYENGINE_DB_READONLY_PASSWORD_SECRET is required}"
: "${POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET:?POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET is required}"

bash .github/scripts/validate_database_environment.sh cloud-sql

readonly_password="$(
  gcloud secrets versions access latest \
    --secret "${POLICYENGINE_DB_READONLY_PASSWORD_SECRET}" \
    --project policyengine-api
)"
migration_password="$(
  gcloud secrets versions access latest \
    --secret "${POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET}" \
    --project policyengine-api
)"

if [[ -z "${readonly_password}" || -z "${migration_password}" ]]; then
  echo "Cloud SQL database credentials must not be empty." >&2
  exit 1
fi

printf '::add-mask::%s\n' "${readonly_password}"
printf '::add-mask::%s\n' "${migration_password}"
export POLICYENGINE_DB_READONLY_PASSWORD="${readonly_password}"
export POLICYENGINE_DB_MIGRATION_PASSWORD="${migration_password}"

# Never allow a job-level URL to bypass the credentials fetched for this release.
unset STAGE7_EXISTING_DATABASE_URL ALEMBIC_DATABASE_URL

database_state="$(python scripts/v1_database_migration.py --mode state)"
echo "Detected v1 database state: ${database_state}"

case "${database_state}" in
  head)
    ;;
  pending)
    backup_id="$(bash .github/scripts/create_cloud_sql_backup.sh)"
    python scripts/v1_database_migration.py \
      --mode upgrade \
      --backup-id "${backup_id}"
    ;;
  unversioned | invalid)
    echo "database is unversioned or has invalid Alembic state; automatic baseline stamping is disabled and manual recovery is required" >&2
    exit 1
    ;;
  *)
    echo "Unrecognized v1 database state: ${database_state}" >&2
    exit 1
    ;;
esac

python scripts/v1_database_migration.py --mode verify-head
