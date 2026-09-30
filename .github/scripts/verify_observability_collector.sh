#!/usr/bin/env bash

set -euo pipefail

endpoint="${1:-}"
if [[ -z "${endpoint}" ]]; then
  echo "Usage: $0 COLLECTOR_ENDPOINT" >&2
  exit 1
fi

export COLLECTOR_ID_TOKEN
COLLECTOR_ID_TOKEN="$(gcloud auth print-identity-token --audiences="${endpoint}")"
export GOOGLE_OAUTH_ACCESS_TOKEN
GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"
echo "::add-mask::${COLLECTOR_ID_TOKEN}"
echo "::add-mask::${GOOGLE_OAUTH_ACCESS_TOKEN}"
uv run --no-project --with grpcio --with opentelemetry-proto \
  python .github/scripts/verify_observability_collector.py \
  --endpoint "${endpoint}" \
  --project-id "${OBSERVABILITY_PROJECT_ID}" \
  --metric-location "${OBSERVABILITY_METRIC_LOCATION}"
