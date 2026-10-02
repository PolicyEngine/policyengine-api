#!/usr/bin/env bash

set -euo pipefail
set +x

CLOUD_RUN_PROJECT="${CLOUD_RUN_PROJECT:-policyengine-api}"
CLOUD_RUN_REGION="${CLOUD_RUN_REGION:-us-central1}"
GCLOUD_BIN="${GCLOUD_BIN:-gcloud}"
include_database_password=0
case "${1:-}" in
  "") ;;
  --include-database-password) include_database_password=1 ;;
  *)
    echo "::error::Unknown argument: $1" >&2
    exit 2
    ;;
esac
if [[ "$#" -gt 1 ]]; then
  echo "::error::Expected at most one argument." >&2
  exit 2
fi

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
  local expected_hash
  local stored_hash=""

  if [[ -z "${secret_value}" ]]; then
    echo "::error::Missing required GitHub secret ${env_name}."
    exit 1
  fi

  if ! "${GCLOUD_BIN}" secrets describe "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}" >/dev/null 2>&1; then
    "${GCLOUD_BIN}" secrets create "${secret_name}" \
      --project "${CLOUD_RUN_PROJECT}" \
      --replication-policy automatic
  fi

  expected_hash="$(printf '%s' "${secret_value}" | sha256sum | cut -d ' ' -f 1)"
  if stored_hash="$(
    "${GCLOUD_BIN}" secrets versions access latest \
      --secret "${secret_name}" \
      --project "${CLOUD_RUN_PROJECT}" 2>/dev/null \
      | sha256sum \
      | cut -d ' ' -f 1
  )" && [[ "${stored_hash}" == "${expected_hash}" ]]; then
    echo "Secret Manager already matches ${env_name}; no version added."
  else
    printf '%s' "${secret_value}" | "${GCLOUD_BIN}" secrets versions add \
      "${secret_name}" \
      --project "${CLOUD_RUN_PROJECT}" \
      --data-file=- >/dev/null
    echo "Synchronized ${env_name} to Secret Manager secret ${secret_name}."
  fi

  verify_secret_value "${env_name}" "${secret_name}"
  grant_secret_access "${secret_name}"
  unset secret_value expected_hash stored_hash
}

verify_secret_value() {
  local env_name="$1"
  local secret_name="$2"
  local expected_value="${!env_name:-}"
  local expected_hash
  local stored_hash

  expected_hash="$(printf '%s' "${expected_value}" | sha256sum | cut -d ' ' -f 1)"
  stored_hash="$(
    "${GCLOUD_BIN}" secrets versions access latest \
      --secret "${secret_name}" \
      --project "${CLOUD_RUN_PROJECT}" \
      | sha256sum \
      | cut -d ' ' -f 1
  )"
  if [[ "${stored_hash}" != "${expected_hash}" ]]; then
    echo "::error::Secret Manager value verification failed for ${secret_name}." >&2
    return 1
  fi
  unset stored_hash expected_hash expected_value
  echo "Verified ${env_name} in Secret Manager without printing its value."
}

grant_secret_access() {
  local secret_name="$1"
  local member

  member="serviceAccount:${runtime_service_account}"

  "${GCLOUD_BIN}" secrets add-iam-policy-binding "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --member "${member}" \
    --role roles/secretmanager.secretAccessor >/dev/null

  if ! "${GCLOUD_BIN}" secrets get-iam-policy "${secret_name}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --format=json \
    | jq -e --arg member "${member}" '
        any(
          .bindings[]?;
          .role == "roles/secretmanager.secretAccessor"
          and ((.members // []) | index($member) != null)
        )
      ' >/dev/null; then
    echo "::error::Secret Manager access verification failed for ${CLOUD_RUN_SERVICE}." >&2
    return 1
  fi
  echo "Verified ${CLOUD_RUN_SERVICE} can read ${secret_name}."
}

require_env CLOUD_RUN_SERVICE

runtime_service_account="$(
  "${GCLOUD_BIN}" run services describe "${CLOUD_RUN_SERVICE}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --region "${CLOUD_RUN_REGION}" \
    --platform managed \
    --format='value(spec.template.spec.serviceAccountName)'
)"
if [[ -z "${runtime_service_account}" ]]; then
  echo "::error::Cloud Run service ${CLOUD_RUN_SERVICE} has no runtime service account." >&2
  exit 1
fi

if [[ "${include_database_password}" -eq 1 ]]; then
  require_env CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET
  db_password_secret_version="${CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET##*:}"
  db_password_secret_resource="${CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET%:*}"
  db_password_secret_name="${db_password_secret_resource##*/}"
  if [[ "${db_password_secret_version}" != "latest" \
    || -z "${db_password_secret_name}" ]]; then
    echo "::error::CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET must name a :latest secret version." >&2
    exit 1
  fi
  sync_secret POLICYENGINE_DB_PASSWORD "${db_password_secret_name}"
fi
sync_secret POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN policyengine-api-prod-github-microdata-token
sync_secret OPENAI_API_KEY policyengine-api-prod-openai-api-key
sync_secret PE_UK_PRIVATE_HF_READ_TOKEN pe-uk-private-hf-read-token
