#!/usr/bin/env bash

set -euo pipefail

: "${APP_ENGINE_VERSION:?APP_ENGINE_VERSION is required}"

APP_ENGINE_PROMOTE="${APP_ENGINE_PROMOTE:-0}"
APP_ENGINE_SERVICE_ACCOUNT="${APP_ENGINE_SERVICE_ACCOUNT:-github-deployment@policyengine-api.iam.gserviceaccount.com}"

cleanup() {
  rm -f app.yaml Dockerfile start.sh .gac.json .dbpw
}

trap cleanup EXIT

python gcp/export.py
cp gcp/policyengine_api/app.yaml .
cp gcp/policyengine_api/Dockerfile .
cp gcp/policyengine_api/start.sh .

gcloud config set app/cloud_build_timeout 2400

deploy_args=(
  app.yaml
  "--service-account=${APP_ENGINE_SERVICE_ACCOUNT}"
  "--version=${APP_ENGINE_VERSION}"
)

if [[ -n "${APP_ENGINE_PROJECT:-}" ]]; then
  deploy_args+=("--project=${APP_ENGINE_PROJECT}")
fi

if [[ "${APP_ENGINE_PROMOTE}" != "1" ]]; then
  deploy_args+=("--no-promote")
fi

yes | gcloud app deploy "${deploy_args[@]}"
