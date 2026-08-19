#!/usr/bin/env bash

set -euo pipefail

APP_ENGINE_IMAGE_TAG="${APP_ENGINE_IMAGE_TAG:-policyengine-api-app-engine:test}"
APP_ENGINE_PLATFORM="${APP_ENGINE_PLATFORM:-linux/amd64}"

cleanup() {
  rm -f app.yaml Dockerfile start.sh
}

trap cleanup EXIT

bash .github/scripts/prepare_app_engine_bundle.sh

docker build --platform "${APP_ENGINE_PLATFORM}" -t "${APP_ENGINE_IMAGE_TAG}" .
