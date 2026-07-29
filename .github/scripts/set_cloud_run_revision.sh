#!/usr/bin/env bash

# Assign all stable Cloud Run service traffic to one exact, ready revision.
# The expected-current guard prevents this workflow from overwriting a traffic
# change made after its candidate deployment. Rollback uses the same script
# with the previous and candidate revisions swapped.

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

cloud_run_require_env \
  CLOUD_RUN_PROJECT \
  CLOUD_RUN_REGION \
  CLOUD_RUN_SERVICE \
  CLOUD_RUN_TARGET_REVISION \
  CLOUD_RUN_EXPECTED_CURRENT_REVISION

target_revision="${CLOUD_RUN_TARGET_REVISION}"
expected_current_revision="${CLOUD_RUN_EXPECTED_CURRENT_REVISION}"

for revision in "${target_revision}" "${expected_current_revision}"; do
  case "${revision}" in
    [Ll][Aa][Tt][Ee][Ss][Tt])
      echo "Cloud Run traffic targets must be exact; LATEST is not allowed" >&2
      exit 2
      ;;
  esac
done

gcloud_bin="${GCLOUD_BIN:-gcloud}"

if [[ "${CLOUD_RUN_DRY_RUN:-0}" == "1" ]]; then
  cloud_run_run "${gcloud_bin}" run services update-traffic \
    "${CLOUD_RUN_SERVICE}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --region "${CLOUD_RUN_REGION}" \
    --platform managed \
    --to-revisions "${target_revision}=100"
  exit 0
fi

active_revision() {
  jq -er '
    [
      .status.traffic[]?
      | select((.percent // 0) == 100)
      | .revisionName
      | select(type == "string" and length > 0)
    ]
    | if length == 1 then .[0]
      else error("service must have exactly one revision at 100 percent")
      end
  '
}

service_json="$("${gcloud_bin}" run services describe "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --format=json)"
current_revision="$(active_revision <<<"${service_json}")"

if [[ "${current_revision}" != "${expected_current_revision}" ]]; then
  printf 'Stable traffic changed after deployment: expected %s, found %s\n' \
    "${expected_current_revision}" "${current_revision}" >&2
  exit 2
fi

revision_json="$("${gcloud_bin}" run revisions describe "${target_revision}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --format=json)"
revision_service="$(jq -r \
  '.metadata.labels["serving.knative.dev/service"] // empty' \
  <<<"${revision_json}")"

if [[ "${revision_service}" != "${CLOUD_RUN_SERVICE}" ]]; then
  printf 'Revision %s belongs to %s, not %s\n' \
    "${target_revision}" "${revision_service:-an unknown service}" \
    "${CLOUD_RUN_SERVICE}" >&2
  exit 2
fi

if ! jq -e '
  .status.conditions[]?
  | select(.type == "Ready" and .status == "True")
' >/dev/null <<<"${revision_json}"; then
  printf 'Revision %s is not Ready\n' "${target_revision}" >&2
  exit 2
fi

"${gcloud_bin}" run services update-traffic "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --to-revisions "${target_revision}=100"

updated_service_json="$("${gcloud_bin}" run services describe \
  "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --format=json)"
updated_revision="$(active_revision <<<"${updated_service_json}")"

if [[ "${updated_revision}" != "${target_revision}" ]]; then
  printf 'Traffic update did not activate %s; found %s\n' \
    "${target_revision}" "${updated_revision}" >&2
  exit 2
fi
