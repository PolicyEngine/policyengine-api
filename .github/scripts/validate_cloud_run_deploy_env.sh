#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
source .github/scripts/simulation_entrypoint_env.sh
cloud_run_set_defaults

# Cloud Run rejects deploys where the traffic tag and service name together
# exceed 46 characters (they form the tag URL's DNS label). Fail fast here
# with a clear message instead of at gcloud.
combined_length=$(( ${#CLOUD_RUN_TAG} + ${#CLOUD_RUN_SERVICE} ))
if (( combined_length > 46 )); then
  echo "Cloud Run tag '${CLOUD_RUN_TAG}' (${#CLOUD_RUN_TAG}) + service '${CLOUD_RUN_SERVICE}' (${#CLOUD_RUN_SERVICE}) = ${combined_length} characters exceeds Cloud Run's 46-character combined limit." >&2
  exit 1
fi

cloud_run_require_env \
  CLOUD_RUN_PROJECT \
  CLOUD_RUN_REGION \
  CLOUD_RUN_SERVICE \
  CLOUD_RUN_ARTIFACT_REPOSITORY \
  CLOUD_RUN_IMAGE_URI \
  CLOUD_RUN_TAG \
  CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT \
  POLICYENGINE_DB_INSTANCE_CONNECTION_NAME \
  CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET \
  CLOUD_RUN_GITHUB_MICRODATA_TOKEN_SECRET \
  CLOUD_RUN_OPENAI_API_KEY_SECRET \
  CLOUD_RUN_HUGGING_FACE_TOKEN_SECRET \
  CLOUD_RUN_RUNTIME_CACHE_URL_SECRET \
  CLOUD_RUN_RUNTIME_CACHE_CA_CERT_SECRET \
  CLOUD_RUN_RUNTIME_CACHE_ENVIRONMENT \
  CLOUD_RUN_VPC_NETWORK \
  CLOUD_RUN_VPC_SUBNET \
  CLOUD_RUN_VPC_EGRESS \
  V2_SUPABASE_PROJECT_REF \
  V2_SUPABASE_ENVIRONMENT \
  SIM_ENTRYPOINT \
  ROUTE_IMPL_HEALTH \
  ROUTE_IMPL_SPECIFICATION \
  ROUTE_IMPL_METADATA \
  GATEWAY_AUTH_ISSUER \
  GATEWAY_AUTH_AUDIENCE \
  GATEWAY_AUTH_CLIENT_ID \
  GATEWAY_AUTH_CLIENT_SECRET_RESOURCE

for selector in \
  ROUTE_IMPL_HEALTH \
  ROUTE_IMPL_SPECIFICATION \
  ROUTE_IMPL_METADATA; do
  value="${!selector}"
  case "${value}" in
    flask_fallback|fastapi_native) ;;
    *)
      printf '%s=%s is invalid; expected flask_fallback or fastapi_native\n' \
        "${selector}" "${value}" >&2
      exit 1
      ;;
  esac
done

selected_url_env="$(
  simulation_entrypoint_url_env_name "${SIM_ENTRYPOINT}"
)"
cloud_run_require_env "${selected_url_env}"
