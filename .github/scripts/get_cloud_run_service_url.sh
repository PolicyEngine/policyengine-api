#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

if [[ "${CLOUD_RUN_DRY_RUN:-0}" == "1" ]]; then
  echo "https://${CLOUD_RUN_SERVICE}-dry-run.a.run.app"
  exit 0
fi

gcloud run services describe "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --format 'value(status.url)'
