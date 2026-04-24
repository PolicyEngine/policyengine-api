#!/usr/bin/env bash

set -euo pipefail

health_url="${1:?health check URL is required}"
timeout_seconds="${HEALTH_CHECK_TIMEOUT_SECONDS:-900}"
interval_seconds="${HEALTH_CHECK_INTERVAL_SECONDS:-10}"
deadline=$((SECONDS + timeout_seconds))

while (( SECONDS < deadline )); do
  if curl --silent --show-error --fail "${health_url}" >/dev/null; then
    exit 0
  fi
  sleep "${interval_seconds}"
done

echo "Timed out waiting for healthy response from ${health_url}" >&2
exit 1
