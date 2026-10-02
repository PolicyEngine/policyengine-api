#!/usr/bin/env bash

set -euo pipefail
set +x

CLOUD_RUN_PROJECT="${CLOUD_RUN_PROJECT:-policyengine-api}"
CLOUD_RUN_REGION="${CLOUD_RUN_REGION:-us-central1}"

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

verify_secret_value() {
  local env_name="$1"
  local secret_name="$2"
  local expected_value="${!env_name:-}"
  local stored_value

  stored_value="$(gcloud secrets versions access latest \
    --secret "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}")"
  if [[ "${stored_value}" != "${expected_value}" ]]; then
    echo "::error::Secret Manager value verification failed for ${secret_name}." >&2
    return 1
  fi
  unset stored_value expected_value
  echo "Verified ${env_name} in Secret Manager without printing its value."
}

grant_secret_access_to_cloud_run_service() {
  local secret_name="$1"
  local service_name="$2"
  local runtime_service_account
  local member

  runtime_service_account="$(gcloud run services describe "${service_name}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --region "${CLOUD_RUN_REGION}" \
    --platform managed \
    --format='value(spec.template.spec.serviceAccountName)')"
  if [[ -z "${runtime_service_account}" ]]; then
    echo "::error::Cloud Run service ${service_name} has no runtime service account." >&2
    return 1
  fi
  member="serviceAccount:${runtime_service_account}"

  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --member "${member}" \
    --role roles/secretmanager.secretAccessor >/dev/null

  if ! gcloud secrets get-iam-policy "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --format=json \
    | jq -e --arg member "${member}" '
        any(
          .bindings[]?;
          .role == "roles/secretmanager.secretAccessor"
          and ((.members // []) | index($member) != null)
        )
      ' >/dev/null; then
    echo "::error::Secret Manager access verification failed for ${service_name}." >&2
    return 1
  fi
  echo "Verified ${service_name} can read ${secret_name}."
}

require_env CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT

sync_secret POLICYENGINE_DB_PASSWORD policyengine-api-prod-db-password
sync_secret POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN policyengine-api-prod-github-microdata-token
sync_secret OPENAI_API_KEY policyengine-api-prod-openai-api-key
sync_secret PE_UK_PRIVATE_HF_READ_TOKEN pe-uk-private-hf-read-token
verify_secret_value PE_UK_PRIVATE_HF_READ_TOKEN pe-uk-private-hf-read-token
grant_secret_access_to_cloud_run_service \
  pe-uk-private-hf-read-token policyengine-api-staging
grant_secret_access_to_cloud_run_service \
  pe-uk-private-hf-read-token policyengine-api
