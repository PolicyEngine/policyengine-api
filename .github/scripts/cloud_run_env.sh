#!/usr/bin/env bash

cloud_run_set_defaults() {
  CLOUD_RUN_PROJECT="${CLOUD_RUN_PROJECT:-policyengine-api}"
  CLOUD_RUN_REGION="${CLOUD_RUN_REGION:-us-central1}"
  CLOUD_RUN_SERVICE="${CLOUD_RUN_SERVICE:-policyengine-api}"
  CLOUD_RUN_ARTIFACT_REPOSITORY="${CLOUD_RUN_ARTIFACT_REPOSITORY:-policyengine-api}"
  # Image name stays fixed across services: the production deploy reuses the
  # image built by the staging track, so it must not embed the service name.
  CLOUD_RUN_IMAGE_NAME="${CLOUD_RUN_IMAGE_NAME:-policyengine-api}"
  CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT="${CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT:-policyengine-api-cr-runtime@policyengine-api.iam.gserviceaccount.com}"
  CLOUD_RUN_CLOUD_SQL_INSTANCE="${CLOUD_RUN_CLOUD_SQL_INSTANCE:-policyengine-api:us-central1:policyengine-api-data}"
  CLOUD_RUN_CPU="${CLOUD_RUN_CPU:-4}"
  CLOUD_RUN_MEMORY="${CLOUD_RUN_MEMORY:-16Gi}"
  CLOUD_RUN_TIMEOUT="${CLOUD_RUN_TIMEOUT:-300}"
  CLOUD_RUN_MIN_INSTANCES="${CLOUD_RUN_MIN_INSTANCES:-0}"
  CLOUD_RUN_MAX_INSTANCES="${CLOUD_RUN_MAX_INSTANCES:-1}"
  # Runtime shape from the Stage 2 capacity qualification
  # (docs/migration/history/pr4-stage2-runtime-timing.md). Both values are
  # pinned explicitly on every deploy: gcloud inherits unspecified template
  # fields, and `--concurrency default` resolves to the platform default
  # (640), not the historical 80.
  CLOUD_RUN_CONCURRENCY="${CLOUD_RUN_CONCURRENCY:-4}"
  CLOUD_RUN_WEB_CONCURRENCY="${CLOUD_RUN_WEB_CONCURRENCY:-2}"
  CLOUD_RUN_PORT="${CLOUD_RUN_PORT:-8080}"
  CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET="${CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET:-policyengine-api-prod-db-password:latest}"
  CLOUD_RUN_GITHUB_MICRODATA_TOKEN_SECRET="${CLOUD_RUN_GITHUB_MICRODATA_TOKEN_SECRET:-policyengine-api-prod-github-microdata-token:latest}"
  CLOUD_RUN_ANTHROPIC_API_KEY_SECRET="${CLOUD_RUN_ANTHROPIC_API_KEY_SECRET:-policyengine-api-prod-anthropic-api-key:latest}"
  CLOUD_RUN_OPENAI_API_KEY_SECRET="${CLOUD_RUN_OPENAI_API_KEY_SECRET:-policyengine-api-prod-openai-api-key:latest}"
  CLOUD_RUN_HUGGING_FACE_TOKEN_SECRET="${CLOUD_RUN_HUGGING_FACE_TOKEN_SECRET:-policyengine-api-prod-hugging-face-token:latest}"

  local sha
  sha="${GITHUB_SHA:-local}"
  CLOUD_RUN_IMAGE_TAG="${CLOUD_RUN_IMAGE_TAG:-${sha}}"
  CLOUD_RUN_IMAGE_URI="${CLOUD_RUN_IMAGE_URI:-${CLOUD_RUN_REGION}-docker.pkg.dev/${CLOUD_RUN_PROJECT}/${CLOUD_RUN_ARTIFACT_REPOSITORY}/${CLOUD_RUN_IMAGE_NAME}:${CLOUD_RUN_IMAGE_TAG}}"

  local short_sha
  short_sha="${sha:0:7}"
  CLOUD_RUN_TAG="${CLOUD_RUN_TAG:-stage3-${GITHUB_RUN_NUMBER:-local}-${short_sha}}"

  export CLOUD_RUN_PROJECT
  export CLOUD_RUN_REGION
  export CLOUD_RUN_SERVICE
  export CLOUD_RUN_ARTIFACT_REPOSITORY
  export CLOUD_RUN_IMAGE_NAME
  export CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT
  export CLOUD_RUN_CLOUD_SQL_INSTANCE
  export CLOUD_RUN_CPU
  export CLOUD_RUN_MEMORY
  export CLOUD_RUN_TIMEOUT
  export CLOUD_RUN_MIN_INSTANCES
  export CLOUD_RUN_MAX_INSTANCES
  export CLOUD_RUN_CONCURRENCY
  export CLOUD_RUN_WEB_CONCURRENCY
  export CLOUD_RUN_PORT
  export CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET
  export CLOUD_RUN_GITHUB_MICRODATA_TOKEN_SECRET
  export CLOUD_RUN_ANTHROPIC_API_KEY_SECRET
  export CLOUD_RUN_OPENAI_API_KEY_SECRET
  export CLOUD_RUN_HUGGING_FACE_TOKEN_SECRET
  export CLOUD_RUN_IMAGE_TAG
  export CLOUD_RUN_IMAGE_URI
  export CLOUD_RUN_TAG
}

cloud_run_require_env() {
  local missing=()
  local name

  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("${name}")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "Missing required Cloud Run deployment configuration: ${missing[*]}" >&2
    return 1
  fi
}

cloud_run_run() {
  if [[ "${CLOUD_RUN_DRY_RUN:-0}" == "1" ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi

  "$@"
}
