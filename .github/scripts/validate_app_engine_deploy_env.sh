#!/usr/bin/env bash

set -euo pipefail

required=(
  SIMULATION_ENTRYPOINT_URL
  OLD_SIMULATION_GATEWAY_URL
  SIM_ENTRYPOINT
  GATEWAY_AUTH_ISSUER
  GATEWAY_AUTH_AUDIENCE
  GATEWAY_AUTH_CLIENT_ID
  GATEWAY_AUTH_CLIENT_SECRET_RESOURCE
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
