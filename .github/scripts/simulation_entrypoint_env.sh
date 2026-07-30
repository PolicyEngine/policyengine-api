#!/usr/bin/env bash

# Shared selected-mode helpers for deployment and compatibility checks.
# The legacy SIMULATION_API_URL secret is intentionally unsupported: its value
# is opaque and must not influence which upstream API v1 calls.

simulation_entrypoint_url_env_name() {
  local entrypoint="${1:-}"

  case "${entrypoint}" in
    old_gateway_direct)
      printf '%s\n' "OLD_SIMULATION_GATEWAY_URL"
      ;;
    cloud_run_simulation_entrypoint)
      printf '%s\n' "SIMULATION_ENTRYPOINT_URL"
      ;;
    "")
      echo "SIM_ENTRYPOINT is required" >&2
      return 1
      ;;
    *)
      printf 'SIM_ENTRYPOINT=%q is invalid; expected old_gateway_direct or cloud_run_simulation_entrypoint\n' \
        "${entrypoint}" >&2
      return 1
      ;;
  esac
}

simulation_entrypoint_selected_url() {
  local url_env_name
  local url

  url_env_name="$(simulation_entrypoint_url_env_name "${1:-}")" || return
  url="${!url_env_name:-}"

  if [[ -z "${url}" ]]; then
    printf '%s is required when SIM_ENTRYPOINT=%s\n' \
      "${url_env_name}" "${1:-}" >&2
    return 1
  fi

  printf '%s\n' "${url}"
}
