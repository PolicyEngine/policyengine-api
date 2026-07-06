#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
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
  CLOUD_RUN_CLOUD_SQL_INSTANCE \
  CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET \
  CLOUD_RUN_GITHUB_MICRODATA_TOKEN_SECRET \
  CLOUD_RUN_ANTHROPIC_API_KEY_SECRET \
  CLOUD_RUN_OPENAI_API_KEY_SECRET \
  CLOUD_RUN_HUGGING_FACE_TOKEN_SECRET \
  SIMULATION_API_URL \
  GATEWAY_AUTH_ISSUER \
  GATEWAY_AUTH_AUDIENCE \
  GATEWAY_AUTH_CLIENT_ID \
  GATEWAY_AUTH_CLIENT_SECRET_RESOURCE
