#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

cloud_run_require_env \
  CLOUD_RUN_PROJECT \
  CLOUD_RUN_REGION \
  CLOUD_RUN_SERVICE \
  CLOUD_RUN_TAG

cloud_run_run gcloud run services update-traffic "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --to-tags "${CLOUD_RUN_TAG}=100"
