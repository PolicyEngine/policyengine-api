#!/usr/bin/env bash

set -euo pipefail

endpoint="${1:-}"
if [[ -z "${endpoint}" ]]; then
  echo "Usage: $0 COLLECTOR_ENDPOINT" >&2
  exit 1
fi

# The workflow's auth step mints COLLECTOR_ID_TOKEN for the collector's URL:
# gcloud can't mint an identity token with an audience from a workload
# identity federation credential.
if [[ -z "${COLLECTOR_ID_TOKEN:-}" ]]; then
  echo "COLLECTOR_ID_TOKEN is not set: mint an identity token for ${endpoint} first" >&2
  exit 1
fi
export COLLECTOR_ID_TOKEN
export GOOGLE_OAUTH_ACCESS_TOKEN
GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"
echo "::add-mask::${COLLECTOR_ID_TOKEN}"
echo "::add-mask::${GOOGLE_OAUTH_ACCESS_TOKEN}"
uv run --no-project --with grpcio --with opentelemetry-proto \
  python .github/scripts/verify_observability_collector.py \
  --endpoint "${endpoint}" \
  --project-id "${OBSERVABILITY_PROJECT_ID}" \
  --metric-location "${OBSERVABILITY_METRIC_LOCATION}"
