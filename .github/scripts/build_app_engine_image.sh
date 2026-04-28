#!/usr/bin/env bash

set -euo pipefail

APP_ENGINE_IMAGE_TAG="${APP_ENGINE_IMAGE_TAG:-policyengine-api-app-engine:test}"

cleanup() {
  rm -f app.yaml Dockerfile start.sh .dbpw
}

trap cleanup EXIT

bash .github/scripts/prepare_app_engine_bundle.sh

docker build -t "${APP_ENGINE_IMAGE_TAG}" .
