#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

bash .github/scripts/validate_cloud_run_deploy_env.sh

env_vars=(
  "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME=${CLOUD_RUN_CLOUD_SQL_INSTANCE}"
  "POLICYENGINE_DB_USER=${POLICYENGINE_DB_USER:-policyengine}"
  "POLICYENGINE_DB_NAME=${POLICYENGINE_DB_NAME:-policyengine}"
  "POLICYENGINE_DB_PASSWORD=${POLICYENGINE_DB_PASSWORD}"
  "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN=${POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN}"
  "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
  "OPENAI_API_KEY=${OPENAI_API_KEY}"
  "HUGGING_FACE_TOKEN=${HUGGING_FACE_TOKEN}"
  "SIMULATION_API_URL=${SIMULATION_API_URL}"
  "GATEWAY_AUTH_REQUIRED=1"
  "GATEWAY_AUTH_ISSUER=${GATEWAY_AUTH_ISSUER}"
  "GATEWAY_AUTH_AUDIENCE=${GATEWAY_AUTH_AUDIENCE}"
  "GATEWAY_AUTH_CLIENT_ID=${GATEWAY_AUTH_CLIENT_ID}"
  "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE=${GATEWAY_AUTH_CLIENT_SECRET_RESOURCE}"
  "CLOUD_RUN_INTERNAL_PROBES=1"
  "API_HOST_BACKEND=cloud_run"
  "SIM_FRONT_DOOR=old_gateway_direct"
  "SIM_COMPUTE_ECONOMY=old_gateway"
  "CLOUD_RUN_REVISION_TAG=${CLOUD_RUN_TAG}"
)

set_env_vars="$(IFS='|'; echo "^|^${env_vars[*]}")"

cloud_run_run gcloud run deploy "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --image "${CLOUD_RUN_IMAGE_URI}" \
  --tag "${CLOUD_RUN_TAG}" \
  --no-traffic \
  --allow-unauthenticated \
  --execution-environment gen2 \
  --service-account "${CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT}" \
  --add-cloudsql-instances "${CLOUD_RUN_CLOUD_SQL_INSTANCE}" \
  --port "${CLOUD_RUN_PORT}" \
  --cpu "${CLOUD_RUN_CPU}" \
  --memory "${CLOUD_RUN_MEMORY}" \
  --timeout "${CLOUD_RUN_TIMEOUT}" \
  --min-instances "${CLOUD_RUN_MIN_INSTANCES}" \
  --max-instances "${CLOUD_RUN_MAX_INSTANCES}" \
  --set-env-vars "${set_env_vars}"
