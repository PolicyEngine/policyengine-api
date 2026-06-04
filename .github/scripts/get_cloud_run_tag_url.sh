#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

if [[ "${CLOUD_RUN_DRY_RUN:-0}" == "1" ]]; then
  echo "https://${CLOUD_RUN_TAG}---${CLOUD_RUN_SERVICE}-dry-run.a.run.app"
  exit 0
fi

gcloud run services describe "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --format json | python -c '
import json
import os
import sys

service = json.load(sys.stdin)
tag = os.environ["CLOUD_RUN_TAG"]
for traffic_target in service.get("status", {}).get("traffic", []):
    if traffic_target.get("tag") == tag and traffic_target.get("url"):
        print(traffic_target["url"])
        raise SystemExit(0)

print(f"Failed to determine Cloud Run URL for tag {tag}", file=sys.stderr)
raise SystemExit(1)
'
