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
  # Revision-level minimum (gcloud --min-instances). MUST stay 0 everywhere: a
  # positive value is set immutably on every new revision, so each tagged
  # no-traffic candidate would pin its own warm instances (a per-tag cost bomb).
  CLOUD_RUN_MIN_INSTANCES="${CLOUD_RUN_MIN_INSTANCES:-0}"
  # Service-level warm floor across all revisions (gcloud --min). This is the
  # correct place to keep instances warm: one floor for whichever revision is
  # serving, with no per-revision pinning. Production sets 2 so the service never
  # cold-starts from zero under the overnight bot trough; staging leaves it 0
  # (scale-to-zero). Rationale in docs/migration/cloud-run-operations.md.
  CLOUD_RUN_SERVICE_MIN_INSTANCES="${CLOUD_RUN_SERVICE_MIN_INSTANCES:-0}"
  CLOUD_RUN_MAX_INSTANCES="${CLOUD_RUN_MAX_INSTANCES:-1}"
  # Stage 2-qualified runtime shape, pinned explicitly on every deploy —
  # rationale in docs/migration/cloud-run-operations.md ("Runtime shape").
  CLOUD_RUN_CONCURRENCY="${CLOUD_RUN_CONCURRENCY:-6}"
  CLOUD_RUN_WEB_CONCURRENCY="${CLOUD_RUN_WEB_CONCURRENCY:-2}"
  CLOUD_RUN_PORT="${CLOUD_RUN_PORT:-8080}"
  # Readiness gate: a TCP probe passes at port-bind, minutes before the app can
  # serve. Window is 180s + 24x10s = 420s; both halves are capped at 240s.
  # Sizing rationale in docs/migration/cloud-run-operations.md.
  CLOUD_RUN_STARTUP_PROBE="${CLOUD_RUN_STARTUP_PROBE:-httpGet.path=/readiness-check,httpGet.port=${CLOUD_RUN_PORT},initialDelaySeconds=180,periodSeconds=10,failureThreshold=24,timeoutSeconds=5}"
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
  export CLOUD_RUN_SERVICE_MIN_INSTANCES
  export CLOUD_RUN_MAX_INSTANCES
  export CLOUD_RUN_CONCURRENCY
  export CLOUD_RUN_WEB_CONCURRENCY
  export CLOUD_RUN_PORT
  export CLOUD_RUN_STARTUP_PROBE
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
