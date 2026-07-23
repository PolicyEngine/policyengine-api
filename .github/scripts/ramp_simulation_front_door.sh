#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

new_revision="${SIMULATION_NEW_FRONT_DOOR_REVISION:?SIMULATION_NEW_FRONT_DOOR_REVISION is required}"
direct_revision="${SIMULATION_DIRECT_GATEWAY_REVISION:?SIMULATION_DIRECT_GATEWAY_REVISION is required}"
new_percent="${SIMULATION_NEW_FRONT_DOOR_PERCENT:?SIMULATION_NEW_FRONT_DOOR_PERCENT is required}"

case "${new_percent}" in
  0|5|25|50|100) ;;
  *)
    echo "SIMULATION_NEW_FRONT_DOOR_PERCENT must be one of 0, 5, 25, 50, or 100" >&2
    exit 1
    ;;
esac

if [ "${new_revision}" = "${direct_revision}" ]; then
  echo "New-front-door and direct-gateway revisions must be different" >&2
  exit 1
fi

validate_revision_front_door() {
  local revision="${1:?revision is required}"
  local expected="${2:?expected front door is required}"

  if [[ "${CLOUD_RUN_DRY_RUN:-0}" == "1" ]]; then
    cloud_run_run gcloud run revisions describe "${revision}" \
      --project "${CLOUD_RUN_PROJECT}" \
      --region "${CLOUD_RUN_REGION}" \
      --format=json
    return
  fi

  local revision_json actual
  revision_json="$(gcloud run revisions describe "${revision}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --region "${CLOUD_RUN_REGION}" \
    --format=json)"
  actual="$(jq -er '.spec.containers[0].env[] | select(.name == "SIM_FRONT_DOOR") | .value' <<<"${revision_json}")"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Revision ${revision} has SIM_FRONT_DOOR=${actual}; expected ${expected}" >&2
    exit 1
  fi
}

validate_revision_front_door "${new_revision}" cloud_run_simulation_api
validate_revision_front_door "${direct_revision}" old_gateway_direct

if [ "${new_percent}" = "0" ]; then
  traffic="${direct_revision}=100"
elif [ "${new_percent}" = "100" ]; then
  traffic="${new_revision}=100"
else
  direct_percent=$((100 - new_percent))
  traffic="${new_revision}=${new_percent},${direct_revision}=${direct_percent}"
fi

cloud_run_run gcloud run services update-traffic "${CLOUD_RUN_SERVICE}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --region "${CLOUD_RUN_REGION}" \
  --platform managed \
  --to-revisions "${traffic}"
