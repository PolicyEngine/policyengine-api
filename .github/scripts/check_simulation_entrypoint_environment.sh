#!/usr/bin/env bash

# Check that a deployment environment calls its own Simulation Entrypoint:
# staging must call the staging service and production the production
# service. The entrypoint names the Cloud Run revision that served a request
# in a response header, and a Cloud Run revision name is its service name
# followed by a five-digit number and a three-character suffix.
#
# The old gateway (SIM_ENTRYPOINT=old_gateway_direct) is one shared Modal app
# that reports no environment, so it is not checked.
#
# Required env vars: DEPLOYMENT_ENVIRONMENT (staging or production),
# SIM_ENTRYPOINT, and the URL variable SIM_ENTRYPOINT selects.

set -euo pipefail

source .github/scripts/simulation_entrypoint_env.sh

deployment_environment="${DEPLOYMENT_ENVIRONMENT:-}"
case "${deployment_environment}" in
  staging)
    expected_service="policyengine-simulation-entry-staging"
    ;;
  production)
    expected_service="policyengine-simulation-entry"
    ;;
  *)
    printf 'DEPLOYMENT_ENVIRONMENT must be staging or production, not %q\n' \
      "${deployment_environment}" >&2
    exit 2
    ;;
esac

if [[ "${SIM_ENTRYPOINT:-}" == "old_gateway_direct" ]]; then
  printf 'SIM_ENTRYPOINT=old_gateway_direct: the shared old gateway reports no environment, so there is nothing to check\n'
  exit 0
fi

simulation_url="$(simulation_entrypoint_selected_url "${SIM_ENTRYPOINT:-}")"
simulation_url="${simulation_url%/}"

health_response="$(
  curl --fail --silent --show-error --include \
    --connect-timeout 10 --max-time 60 \
    "${simulation_url}/health"
)"

served_revision="$(
  awk '
    tolower($1) == "x-policyengine-simulation-revision:" {
      gsub("\r", "", $2)
      print $2
    }
  ' <<<"${health_response}" |
    tail -n 1
)"

if [[ -z "${served_revision}" ]]; then
  printf '%s/health did not name a Simulation Entrypoint revision; the %s deployment must call the stable URL of %s\n' \
    "${simulation_url}" "${deployment_environment}" "${expected_service}" >&2
  exit 1
fi

if ! [[ "${served_revision}" =~ ^(.+)-[0-9]{5}-[a-z0-9]{3}$ ]]; then
  printf '%s, served by %s, is not a Cloud Run revision name\n' \
    "${served_revision}" "${simulation_url}" >&2
  exit 1
fi
served_service="${BASH_REMATCH[1]}"

if [[ "${served_service}" != "${expected_service}" ]]; then
  printf 'The %s deployment calls %s, which revision %s of %s serves; it must call %s\n' \
    "${deployment_environment}" "${simulation_url}" "${served_revision}" \
    "${served_service}" "${expected_service}" >&2
  exit 1
fi

printf 'The %s deployment calls %s, served by revision %s of %s\n' \
  "${deployment_environment}" "${simulation_url}" "${served_revision}" \
  "${served_service}"
