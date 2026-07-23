#!/usr/bin/env bash

set -euo pipefail

# Poll a freshly deployed service's /readiness-check until it answers 200.
#
# The staging services are scale-to-zero, so a candidate revision is cold on its
# first request and must import the tax-benefit system (~200s for the US system)
# before it can serve a calculate. Run as a gate job ahead of the smoke suites,
# this makes the tests hit a warm instance instead of racing the cold-start
# import (which otherwise times out and blocks the production deploy).

url="${SERVICE_URL:?SERVICE_URL is required}"
url="${url%/}"
deadline_seconds="${READINESS_DEADLINE_SECONDS:-480}"
poll_interval_seconds="${READINESS_POLL_INTERVAL_SECONDS:-5}"
request_timeout_seconds="${READINESS_REQUEST_TIMEOUT_SECONDS:-30}"

deadline=$(( SECONDS + deadline_seconds ))
attempt=0

while true; do
  attempt=$(( attempt + 1 ))
  status="$(curl -s -o /dev/null -w '%{http_code}' \
    --max-time "${request_timeout_seconds}" "${url}/readiness-check" || true)"

  if [[ "${status}" == "200" ]]; then
    echo "Ready after ${attempt} attempt(s): ${url}/readiness-check -> 200"
    exit 0
  fi

  if (( SECONDS >= deadline )); then
    echo "::error::${url} did not become ready within ${deadline_seconds}s (last status: ${status:-none})" >&2
    exit 1
  fi

  echo "Attempt ${attempt}: ${url}/readiness-check -> ${status:-no response}; retrying in ${poll_interval_seconds}s"
  sleep "${poll_interval_seconds}"
done
