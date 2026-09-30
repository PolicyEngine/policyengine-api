#!/usr/bin/env bash

set -euo pipefail

required=(
  OBSERVABILITY_PROJECT_ID
  OBSERVABILITY_COLLECTOR_REGION
  OBSERVABILITY_COLLECTOR_SERVICE
  OBSERVABILITY_COLLECTOR_ARTIFACT_REPOSITORY
  OBSERVABILITY_COLLECTOR_IMAGE_NAME
  OBSERVABILITY_COLLECTOR_SERVICE_ACCOUNT
  OBSERVABILITY_METRIC_LOCATION
  GITHUB_SHA
)

missing=()
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("${name}")
  fi
done
if (( ${#missing[@]} > 0 )); then
  echo "Missing collector deployment configuration: ${missing[*]}" >&2
  exit 1
fi

[[ "${OBSERVABILITY_PROJECT_ID}" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] \
  || { echo "OBSERVABILITY_PROJECT_ID is invalid." >&2; exit 1; }
[[ "${OBSERVABILITY_COLLECTOR_REGION}" =~ ^[a-z]+-[a-z]+[0-9]+$ ]] \
  || { echo "OBSERVABILITY_COLLECTOR_REGION is invalid." >&2; exit 1; }
[[ "${OBSERVABILITY_COLLECTOR_SERVICE}" =~ ^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$ ]] \
  || { echo "OBSERVABILITY_COLLECTOR_SERVICE is invalid." >&2; exit 1; }
[[ "${OBSERVABILITY_COLLECTOR_ARTIFACT_REPOSITORY}" =~ ^[a-z][a-z0-9._-]{0,62}$ ]] \
  || { echo "OBSERVABILITY_COLLECTOR_ARTIFACT_REPOSITORY is invalid." >&2; exit 1; }
[[ "${OBSERVABILITY_COLLECTOR_IMAGE_NAME}" =~ ^[a-z0-9][a-z0-9._-]{0,127}$ ]] \
  || { echo "OBSERVABILITY_COLLECTOR_IMAGE_NAME is invalid." >&2; exit 1; }
[[ "${OBSERVABILITY_COLLECTOR_SERVICE_ACCOUNT}" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com$ ]] \
  || { echo "OBSERVABILITY_COLLECTOR_SERVICE_ACCOUNT is invalid." >&2; exit 1; }
[[ "${OBSERVABILITY_METRIC_LOCATION}" =~ ^[a-z]+-[a-z]+[0-9]+$ ]] \
  || { echo "OBSERVABILITY_METRIC_LOCATION is invalid." >&2; exit 1; }
[[ "${GITHUB_SHA}" =~ ^[0-9a-f]{40}$ ]] \
  || { echo "GITHUB_SHA must be a 40-character lowercase commit SHA." >&2; exit 1; }

registry="${OBSERVABILITY_COLLECTOR_REGION}-docker.pkg.dev"
image_uri="${registry}/${OBSERVABILITY_PROJECT_ID}/${OBSERVABILITY_COLLECTOR_ARTIFACT_REPOSITORY}/${OBSERVABILITY_COLLECTOR_IMAGE_NAME}:${GITHUB_SHA}"

gcloud artifacts repositories describe \
  "${OBSERVABILITY_COLLECTOR_ARTIFACT_REPOSITORY}" \
  --project "${OBSERVABILITY_PROJECT_ID}" \
  --location "${OBSERVABILITY_COLLECTOR_REGION}" >/dev/null
gcloud auth configure-docker "${registry}" --quiet
docker build \
  --platform linux/amd64 \
  --file gcp/observability/collector/Dockerfile \
  --tag "${image_uri}" \
  gcp/observability/collector
docker push "${image_uri}"

gcloud run deploy "${OBSERVABILITY_COLLECTOR_SERVICE}" \
  --project "${OBSERVABILITY_PROJECT_ID}" \
  --region "${OBSERVABILITY_COLLECTOR_REGION}" \
  --platform managed \
  --image "${image_uri}" \
  --service-account "${OBSERVABILITY_COLLECTOR_SERVICE_ACCOUNT}" \
  --invoker-iam-check \
  --execution-environment gen2 \
  --port 8080 \
  --use-http2 \
  --cpu 1 \
  --no-cpu-throttling \
  --cpu-boost \
  --memory 512Mi \
  --timeout 30 \
  --min 1 \
  --max 10 \
  --concurrency 100 \
  --startup-probe \
    'httpGet.path=/,httpGet.port=13133,periodSeconds=2,failureThreshold=30,timeoutSeconds=1' \
  --liveness-probe \
    'httpGet.path=/,httpGet.port=13133,periodSeconds=30,failureThreshold=3,timeoutSeconds=2' \
  --set-env-vars \
    "OBSERVABILITY_PROJECT_ID=${OBSERVABILITY_PROJECT_ID},OBSERVABILITY_METRIC_LOCATION=${OBSERVABILITY_METRIC_LOCATION}" \
  --quiet

service_json="$(
  gcloud run services describe "${OBSERVABILITY_COLLECTOR_SERVICE}" \
    --project "${OBSERVABILITY_PROJECT_ID}" \
    --region "${OBSERVABILITY_COLLECTOR_REGION}" \
    --format=json
)"
revision="$(jq -r '.status.latestReadyRevisionName // ""' <<< "${service_json}")"
service_url="$(jq -r '.status.url // ""' <<< "${service_json}")"
ready="$(
  jq -r \
    '[.status.conditions[]? | select(.type == "Ready") | .status][0] // ""' \
    <<< "${service_json}"
)"

for public_member in allUsers allAuthenticatedUsers; do
  if gcloud run services get-iam-policy \
    "${OBSERVABILITY_COLLECTOR_SERVICE}" \
    --project "${OBSERVABILITY_PROJECT_ID}" \
    --region "${OBSERVABILITY_COLLECTOR_REGION}" \
    --flatten='bindings[].members' \
    --filter="bindings.role=roles/run.invoker AND bindings.members=${public_member}" \
    --format='value(bindings.members)' | grep -qx "${public_member}"; then
    gcloud run services remove-iam-policy-binding \
      "${OBSERVABILITY_COLLECTOR_SERVICE}" \
      --project "${OBSERVABILITY_PROJECT_ID}" \
      --region "${OBSERVABILITY_COLLECTOR_REGION}" \
      --member="${public_member}" \
      --role=roles/run.invoker \
      --quiet
  fi
done

public_members="$(
  gcloud run services get-iam-policy \
    "${OBSERVABILITY_COLLECTOR_SERVICE}" \
    --project "${OBSERVABILITY_PROJECT_ID}" \
    --region "${OBSERVABILITY_COLLECTOR_REGION}" \
    --flatten='bindings[].members' \
    --filter='bindings.members:(allUsers OR allAuthenticatedUsers)' \
    --format='value(bindings.members)'
)"
invoker_iam_disabled="$(
  gcloud run services describe "${OBSERVABILITY_COLLECTOR_SERVICE}" \
    --project "${OBSERVABILITY_PROJECT_ID}" \
    --region "${OBSERVABILITY_COLLECTOR_REGION}" \
    --format="value(metadata.annotations.'run.googleapis.com/invoker-iam-disabled')"
)"

if [[ -z "${revision}" || -z "${service_url}" || "${ready}" != "True" ]]; then
  echo "Collector deployment did not produce a healthy ready revision and URL." >&2
  exit 1
fi
if [[ -n "${public_members}" || "${invoker_iam_disabled}" == "true" ]]; then
  echo "Collector Cloud Run service permits unauthenticated invocation." >&2
  exit 1
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "revision=${revision}" >> "${GITHUB_OUTPUT}"
  echo "service_url=${service_url}" >> "${GITHUB_OUTPUT}"
  echo "image_uri=${image_uri}" >> "${GITHUB_OUTPUT}"
fi

printf 'Deployed collector revision %s at %s\n' "${revision}" "${service_url}"
