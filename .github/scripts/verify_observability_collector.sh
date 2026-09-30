#!/usr/bin/env bash

set -euo pipefail

endpoint="${1:-}"
if [[ -z "${endpoint}" ]]; then
  echo "Usage: $0 COLLECTOR_ENDPOINT" >&2
  exit 1
fi

token="$(gcloud auth print-identity-token --audiences="${endpoint}")"
echo "::add-mask::${token}"
uv run --with grpcio --with opentelemetry-proto \
  python .github/scripts/verify_observability_collector.py \
  --endpoint "${endpoint}" \
  --token "${token}"
