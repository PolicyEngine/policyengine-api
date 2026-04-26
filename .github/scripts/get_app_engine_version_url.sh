#!/usr/bin/env bash

set -euo pipefail

: "${APP_ENGINE_VERSION:?APP_ENGINE_VERSION is required}"

APP_ENGINE_SERVICE="${APP_ENGINE_SERVICE:-default}"

browse_args=(
  "${APP_ENGINE_VERSION}"
  "--service=${APP_ENGINE_SERVICE}"
  "--no-launch-browser"
)

if [[ -n "${APP_ENGINE_PROJECT:-}" ]]; then
  browse_args+=("--project=${APP_ENGINE_PROJECT}")
fi

output="$(gcloud app versions browse "${browse_args[@]}" 2>&1)"
url="$(printf '%s\n' "${output}" | grep -Eo 'https://[^[:space:]]+' | tail -n1)"

if [[ -z "${url}" ]]; then
  echo "Failed to determine App Engine version URL" >&2
  printf '%s\n' "${output}" >&2
  exit 1
fi

printf '%s\n' "${url}"
