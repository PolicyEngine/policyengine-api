#!/usr/bin/env bash

set -euo pipefail

: "${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME:?POLICYENGINE_DB_INSTANCE_CONNECTION_NAME is required}"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

instance_id="${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME##*:}"
description="policyengine-api-v1-alembic-${GITHUB_SHA:-manual}"
backup_id="$(
  gcloud sql backups create \
    --project policyengine-api \
    --instance "${instance_id}" \
    --description "${description}" \
    --format 'value(id)'
)"

if [[ -z "${backup_id}" ]]; then
  echo "Cloud SQL did not return a completed backup ID." >&2
  exit 1
fi

printf 'backup_id=%s\n' "${backup_id}" >>"${GITHUB_OUTPUT}"
