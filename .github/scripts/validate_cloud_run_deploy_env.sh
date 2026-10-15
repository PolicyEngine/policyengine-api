#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
source .github/scripts/simulation_entrypoint_env.sh
cloud_run_set_defaults

bash .github/scripts/validate_database_environment.sh runtime

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
  CLOUD_RUN_PE_UK_PRIVATE_HF_READ_TOKEN_SECRET \
  CLOUD_RUN_RUNTIME_CACHE_URL_SECRET \
  CLOUD_RUN_RUNTIME_CACHE_CA_CERT_SECRET \
  CLOUD_RUN_RUNTIME_CACHE_ENVIRONMENT \
  CLOUD_RUN_VPC_NETWORK \
  CLOUD_RUN_VPC_SUBNET \
  CLOUD_RUN_VPC_EGRESS \
  OBSERVABILITY_SERVICE_NAMESPACE \
  OBSERVABILITY_TRACE_PROJECT_ID \
  OTEL_EXPORTER_OTLP_ENDPOINT \
  POLICYENGINE_OTEL_GOOGLE_AUDIENCE \
  V2_SUPABASE_PROJECT_REF \
  V2_SUPABASE_ENVIRONMENT \
  V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE \
  SIM_ENTRYPOINT \
  ROUTE_IMPL_HEALTH \
  ROUTE_IMPL_SPECIFICATION \
  ROUTE_IMPL_METADATA \
  ROUTE_IMPL_POLICY \
  ROUTE_IMPL_HOUSEHOLD \
  DB_READ_POLICY \
  DB_WRITE_POLICY \
  DB_READ_HOUSEHOLD \
  DB_WRITE_HOUSEHOLD \
  GATEWAY_AUTH_ISSUER \
  GATEWAY_AUTH_AUDIENCE \
  GATEWAY_AUTH_CLIENT_ID \
  GATEWAY_AUTH_CLIENT_SECRET_RESOURCE \
  PUBLIC_API_AUTH_REQUIRED

for selector in \
  ROUTE_IMPL_HEALTH \
  ROUTE_IMPL_SPECIFICATION \
  ROUTE_IMPL_METADATA \
  ROUTE_IMPL_POLICY; do
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

if [[ "${ROUTE_IMPL_HOUSEHOLD}" != "flask_fallback" ]]; then
  printf '%s=%s is invalid; expected flask_fallback during Stage 11\n' \
    "ROUTE_IMPL_HOUSEHOLD" "${ROUTE_IMPL_HOUSEHOLD}" >&2
  exit 1
fi

if [[ "${DB_READ_POLICY}" != "cloud_sql" ]]; then
  printf '%s=%s is invalid; expected cloud_sql\n' \
    "DB_READ_POLICY" "${DB_READ_POLICY}" >&2
  exit 1
fi

case "${DB_WRITE_POLICY}" in
  cloud_sql|dual_write) ;;
  *)
    printf '%s=%s is invalid; expected cloud_sql or dual_write\n' \
      "DB_WRITE_POLICY" "${DB_WRITE_POLICY}" >&2
    exit 1
    ;;
esac

if [[ "${DB_READ_HOUSEHOLD}" != "cloud_sql" ]]; then
  printf '%s=%s is invalid; expected cloud_sql\n' \
    "DB_READ_HOUSEHOLD" "${DB_READ_HOUSEHOLD}" >&2
  exit 1
fi

case "${DB_WRITE_HOUSEHOLD}" in
  cloud_sql|dual_write) ;;
  *)
    printf '%s=%s is invalid; expected cloud_sql or dual_write\n' \
      "DB_WRITE_HOUSEHOLD" "${DB_WRITE_HOUSEHOLD}" >&2
    exit 1
    ;;
esac

# Signed-in user routes fail closed without Auth0 settings. When required,
# the issuer and audience must be present; otherwise they are set together
# or not at all.
case "${PUBLIC_API_AUTH_REQUIRED}" in
  0|1) ;;
  *)
    printf '%s=%s is invalid; expected 0 or 1\n' \
      "PUBLIC_API_AUTH_REQUIRED" "${PUBLIC_API_AUTH_REQUIRED}" >&2
    exit 1
    ;;
esac
if [[ "${PUBLIC_API_AUTH_REQUIRED}" == "1" ]]; then
  cloud_run_require_env PUBLIC_API_AUTH_ISSUER PUBLIC_API_AUTH_AUDIENCE
fi
if [[ -n "${PUBLIC_API_AUTH_ISSUER:-}" && -z "${PUBLIC_API_AUTH_AUDIENCE:-}" ]] \
  || [[ -z "${PUBLIC_API_AUTH_ISSUER:-}" && -n "${PUBLIC_API_AUTH_AUDIENCE:-}" ]]; then
  echo "Set both PUBLIC_API_AUTH_ISSUER and PUBLIC_API_AUTH_AUDIENCE, or neither" >&2
  exit 1
fi
if [[ -n "${PUBLIC_API_AUTH_ISSUER:-}" && "${PUBLIC_API_AUTH_ISSUER}" != https://* ]]; then
  echo "PUBLIC_API_AUTH_ISSUER must be an absolute HTTPS URL" >&2
  exit 1
fi

auth0_management_count=0
for name in \
  AUTH0_MANAGEMENT_DOMAIN \
  AUTH0_MANAGEMENT_CLIENT_ID \
  AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE; do
  if [[ -n "${!name:-}" ]]; then
    auth0_management_count=$((auth0_management_count + 1))
  fi
done
if (( auth0_management_count != 0 && auth0_management_count != 3 )); then
  echo "Set AUTH0_MANAGEMENT_DOMAIN, AUTH0_MANAGEMENT_CLIENT_ID, and AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE together, or none" >&2
  exit 1
fi
# The staging live test deletes its own account through DELETE /v2/me. With
# Management API deletion configured, that would delete the CI user from
# Auth0, so only production may configure it.
if (( auth0_management_count != 0 )) && [[ "${DEPLOYMENT_ENVIRONMENT}" != "production" ]]; then
  echo "AUTH0_MANAGEMENT_* settings are production-only; unset them for ${DEPLOYMENT_ENVIRONMENT}" >&2
  exit 1
fi

selected_url_env="$(
  simulation_entrypoint_url_env_name "${SIM_ENTRYPOINT}"
)"
cloud_run_require_env "${selected_url_env}"
