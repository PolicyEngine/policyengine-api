#!/usr/bin/env bash

set -euo pipefail

: "${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME:?POLICYENGINE_DB_INSTANCE_CONNECTION_NAME is required}"

instance_id="${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME##*:}"
description="policyengine-api-v1-alembic-${GITHUB_SHA:-manual}-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
gcloud sql backups create \
  --project policyengine-api \
  --instance "${instance_id}" \
  --description "${description}" \
  --quiet >&2

# `gcloud sql backups create` waits for completion but does not consistently
# emit the created resource with value-format output. Recover the ID from the
# unique workflow description and require the service-reported successful state.
backup_id="$(
  gcloud sql backups list \
    --project policyengine-api \
    --instance "${instance_id}" \
    --filter="description=${description} AND status=SUCCESSFUL" \
    --sort-by='~startTime' \
    --limit=1 \
    --format='value(id)'
)"

if [[ -z "${backup_id}" ]]; then
  echo "Cloud SQL did not return a completed backup ID." >&2
  exit 1
fi

printf '%s\n' "${backup_id}"
