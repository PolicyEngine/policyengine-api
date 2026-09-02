#!/usr/bin/env bash

# Resolve a no-traffic tag once, then pin all later testing and promotion to
# the exact ready revision and immutable image represented by that tag.

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

cloud_run_require_env \
  CLOUD_RUN_PROJECT \
  CLOUD_RUN_REGION \
  CLOUD_RUN_SERVICE \
  CLOUD_RUN_TAG

if [[ "${CLOUD_RUN_DRY_RUN:-0}" == "1" ]]; then
  echo "url=https://${CLOUD_RUN_TAG}---${CLOUD_RUN_SERVICE}-dry-run.a.run.app"
  echo "revision=${CLOUD_RUN_SERVICE}-00002-dry"
  echo "image=${CLOUD_RUN_IMAGE_URI%@*}@sha256:dry-run"
  exit 0
fi

gcloud_bin="${GCLOUD_BIN:-gcloud}"
service_json="$("${gcloud_bin}" run services describe "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --format=json)"
candidate_json="$(jq -cer --arg tag "${CLOUD_RUN_TAG}" '
  [
    .status.traffic[]?
    | select(.tag == $tag)
    | {
        url: (
          .url
          | select(type == "string" and length > 0)
        ),
        revision: (
          .revisionName
          | select(type == "string" and length > 0)
        )
      }
  ]
  | if length == 1 then .[0]
    else error("candidate tag must resolve to exactly one traffic target")
    end
' <<<"${service_json}")"
url="$(jq -er '.url' <<<"${candidate_json}")"
revision="$(jq -er '.revision' <<<"${candidate_json}")"

revision_json="$("${gcloud_bin}" run revisions describe "${revision}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --format=json)"
revision_service="$(jq -r \
  '.metadata.labels["serving.knative.dev/service"] // empty' \
  <<<"${revision_json}")"

if [[ "${revision_service}" != "${CLOUD_RUN_SERVICE}" ]]; then
  printf 'Revision %s belongs to %s, not %s\n' \
    "${revision}" "${revision_service:-an unknown service}" \
    "${CLOUD_RUN_SERVICE}" >&2
  exit 2
fi

if ! jq -e '
  .status.conditions[]?
  | select(.type == "Ready" and .status == "True")
' >/dev/null <<<"${revision_json}"; then
  printf 'Revision %s is not Ready\n' "${revision}" >&2
  exit 2
fi

image="$(jq -er '
  (.status.imageDigest // .spec.containers[0].image)
  | select(type == "string" and contains("@sha256:"))
' <<<"${revision_json}")"

deployment_selector_count=0
for selector in \
  ROUTE_IMPL_HEALTH \
  ROUTE_IMPL_SPECIFICATION \
  ROUTE_IMPL_METADATA \
  ROUTE_IMPL_POLICY \
  DB_READ_POLICY \
  DB_WRITE_POLICY; do
  if [[ -n "${!selector:-}" ]]; then
    deployment_selector_count=$((deployment_selector_count + 1))
  fi
done

if (( deployment_selector_count > 0 && deployment_selector_count < 6 )); then
  echo "All route and policy database selectors are required when verifying candidate configuration" >&2
  exit 2
fi

if (( deployment_selector_count == 6 )); then
  for selector in \
    ROUTE_IMPL_HEALTH \
    ROUTE_IMPL_SPECIFICATION \
    ROUTE_IMPL_METADATA \
    ROUTE_IMPL_POLICY \
    DB_READ_POLICY \
    DB_WRITE_POLICY; do
    expected_value="${!selector}"
    actual_value="$(jq -r --arg name "${selector}" '
      [
        .spec.containers[0].env[]?
        | select(.name == $name)
        | .value
      ]
      | if length == 1 then .[0] else "" end
    ' <<<"${revision_json}")"
    if [[ "${actual_value}" != "${expected_value}" ]]; then
      printf 'Revision %s has %s=%s; expected %s\n' \
        "${revision}" "${selector}" "${actual_value:-<missing>}" \
        "${expected_value}" >&2
      exit 2
    fi
  done
fi

if [[ -n "${CLOUD_RUN_EXPECTED_REVISION:-}" \
  && "${revision}" != "${CLOUD_RUN_EXPECTED_REVISION}" ]]; then
  printf 'Candidate tag %s moved: expected revision %s, found %s\n' \
    "${CLOUD_RUN_TAG}" "${CLOUD_RUN_EXPECTED_REVISION}" "${revision}" >&2
  exit 2
fi

if [[ -n "${CLOUD_RUN_EXPECTED_IMAGE:-}" \
  && "${image}" != "${CLOUD_RUN_EXPECTED_IMAGE}" ]]; then
  printf 'Candidate image changed: expected %s, found %s\n' \
    "${CLOUD_RUN_EXPECTED_IMAGE}" "${image}" >&2
  exit 2
fi

printf 'url=%s\nrevision=%s\nimage=%s\n' "${url}" "${revision}" "${image}"
