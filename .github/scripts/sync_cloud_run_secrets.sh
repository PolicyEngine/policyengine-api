#!/usr/bin/env bash

set -euo pipefail
set +x

CLOUD_RUN_PROJECT="${CLOUD_RUN_PROJECT:-policyengine-api}"

require_env() {
  local env_name="$1"
  if [[ -z "${!env_name:-}" ]]; then
    echo "::error::Missing required workflow environment ${env_name}."
    exit 1
  fi
}

sync_secret() {
  local env_name="$1"
  local secret_name="$2"
  local secret_value="${!env_name:-}"

  if [[ -z "${secret_value}" ]]; then
    echo "::error::Missing required GitHub secret ${env_name}."
    exit 1
  fi

  if ! gcloud secrets describe "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}" >/dev/null 2>&1; then
    gcloud secrets create "${secret_name}" \
      --project "${CLOUD_RUN_PROJECT}" \
      --replication-policy automatic
  fi

  printf '%s' "${secret_value}" | gcloud secrets versions add \
    "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --data-file=- >/dev/null

  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --member "serviceAccount:${CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT}" \
    --role roles/secretmanager.secretAccessor >/dev/null

  echo "Synced ${env_name} to Secret Manager secret ${secret_name}."
}

require_env CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT

sync_secret POLICYENGINE_DB_PASSWORD policyengine-api-prod-db-password
sync_secret POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN policyengine-api-prod-github-microdata-token
sync_secret ANTHROPIC_API_KEY policyengine-api-prod-anthropic-api-key
sync_secret OPENAI_API_KEY policyengine-api-prod-openai-api-key
sync_secret HUGGING_FACE_TOKEN policyengine-api-prod-hugging-face-token
