#!/usr/bin/env bash

set -euo pipefail

: "${APP_ENGINE_VERSION:?APP_ENGINE_VERSION is required}"

APP_ENGINE_SERVICE="${APP_ENGINE_SERVICE:-default}"

promote_args=(
  "${APP_ENGINE_SERVICE}"
  "--splits=${APP_ENGINE_VERSION}=1"
)

if [[ -n "${APP_ENGINE_PROJECT:-}" ]]; then
  promote_args+=("--project=${APP_ENGINE_PROJECT}")
fi

gcloud app services set-traffic "${promote_args[@]}"
