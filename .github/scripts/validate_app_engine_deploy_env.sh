#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/simulation_entrypoint_env.sh

selected_url_env="$(
  simulation_entrypoint_url_env_name "${SIM_ENTRYPOINT:-}"
)"

required=(
  APP_ENGINE_SERVICE_ACCOUNT
  POLICYENGINE_DB_INSTANCE_CONNECTION_NAME
  POLICYENGINE_DB_PASSWORD_SECRET_RESOURCE
  POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN_SECRET_RESOURCE
  ANTHROPIC_API_KEY_SECRET_RESOURCE
  OPENAI_API_KEY_SECRET_RESOURCE
  HUGGING_FACE_TOKEN_SECRET_RESOURCE
  SIM_ENTRYPOINT
  "${selected_url_env}"
  GATEWAY_AUTH_ISSUER
  GATEWAY_AUTH_AUDIENCE
  GATEWAY_AUTH_CLIENT_ID
  GATEWAY_AUTH_CLIENT_SECRET_RESOURCE
  RUNTIME_CACHE_ENVIRONMENT
  RUNTIME_CACHE_URL_SECRET_RESOURCE
  RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE
)

missing=()

for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("$name")
  fi
done

if [[ "${#missing[@]}" -gt 0 ]]; then
  echo "Missing required App Engine deployment configuration: ${missing[*]}" >&2
  exit 1
fi
