#!/usr/bin/env bash

# Stop (deactivate) a single App Engine version.
#
# App Engine Flexible keeps at least one VM running for every SERVING version
# regardless of traffic, so a version left SERVING after its tests keeps costing
# money. Stopping it drops its instances to zero (no billing) while keeping the
# version deployed and restartable (`gcloud app versions start`) for rollback.

set -euo pipefail

: "${APP_ENGINE_VERSION:?APP_ENGINE_VERSION is required}"

APP_ENGINE_SERVICE="${APP_ENGINE_SERVICE:-default}"

stop_args=(
  "${APP_ENGINE_VERSION}"
  "--service=${APP_ENGINE_SERVICE}"
  "--quiet"
)

if [[ -n "${APP_ENGINE_PROJECT:-}" ]]; then
  stop_args+=("--project=${APP_ENGINE_PROJECT}")
fi

echo "Stopping App Engine version ${APP_ENGINE_VERSION} (service ${APP_ENGINE_SERVICE})"
gcloud app versions stop "${stop_args[@]}"
