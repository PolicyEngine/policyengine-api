#!/usr/bin/env bash

# Capture the stable URL and sole 100%-serving revision before a candidate
# deployment. Promotion consumes this revision as its optimistic concurrency
# guard; rollback consumes it as the exact restoration target.

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

cloud_run_require_env \
  CLOUD_RUN_PROJECT \
  CLOUD_RUN_REGION \
  CLOUD_RUN_SERVICE

if [[ "${CLOUD_RUN_DRY_RUN:-0}" == "1" ]]; then
  echo "stable_url=https://${CLOUD_RUN_SERVICE}-dry-run.a.run.app"
  echo "revision=${CLOUD_RUN_SERVICE}-00001-dry"
  exit 0
fi

gcloud_bin="${GCLOUD_BIN:-gcloud}"
service_json="$("${gcloud_bin}" run services describe "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --format=json)"

stable_url="$(jq -er '
  .status.url
  | select(type == "string" and length > 0)
' <<<"${service_json}")"
revision="$(jq -er '
  [
    .status.traffic[]?
    | select((.percent // 0) == 100)
    | .revisionName
    | select(type == "string" and length > 0)
  ]
  | if length == 1 then .[0]
    else error("service must have exactly one revision at 100 percent")
    end
' <<<"${service_json}")"

printf 'stable_url=%s\nrevision=%s\n' "${stable_url}" "${revision}"
