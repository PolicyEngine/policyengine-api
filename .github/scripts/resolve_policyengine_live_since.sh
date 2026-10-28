#!/usr/bin/env bash

# Decide when the policyengine.py (.py) version this deploy installs went live.
# A deploy that keeps the serving revision's .py version keeps that revision's
# date; a new .py version goes live with this deploy. The API redeploys several
# times a day without changing .py, so a plain deploy time would not say how
# long the version has been served.
#
# Inputs: PREVIOUS_CLOUD_RUN_REVISION (the revision serving 100% of traffic,
# from capture_cloud_run_service_state.sh; empty on a first deploy) and the
# usual CLOUD_RUN_* settings. POLICYENGINE_LOCK_FILE and
# POLICYENGINE_LIVE_SINCE_NOW override the lock path and the clock for tests.
#
# Prints DEPLOYED_POLICYENGINE_VERSION=... and POLICYENGINE_VERSION_LIVE_SINCE=...
# The date is recorded only when this deploy is the event (a new .py version
# or a first deploy). When the serving revision has the same version but no
# date (deployed before dates were recorded), or cannot be read, the date is
# left empty (unknown) rather than set to a later, wrong time. A failed lookup
# never fails the deploy.

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

lock_file="${POLICYENGINE_LOCK_FILE:-uv.lock}"
# The same uv.lock reader the daily relock uses; it fails unless policyengine
# is locked at exactly one version.
version="$(python3 .github/scripts/locked_packages.py bundle-version "${lock_file}")"
if [[ -z "${version}" ]]; then
  echo "policyengine is not locked in ${lock_file}" >&2
  exit 1
fi

now="${POLICYENGINE_LIVE_SINCE_NOW:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
live_since="${now}"
previous="${PREVIOUS_CLOUD_RUN_REVISION:-}"

if [[ -n "${previous}" && "${CLOUD_RUN_DRY_RUN:-0}" != "1" ]]; then
  gcloud_bin="${GCLOUD_BIN:-gcloud}"
  if revision_json="$("${gcloud_bin}" run revisions describe "${previous}" \
    --project "${CLOUD_RUN_PROJECT}" \
    --region "${CLOUD_RUN_REGION}" \
    --platform managed \
    --format=json)"; then
    revision_env() {
      jq -r --arg name "$1" '
        [.spec.containers[0].env[]? | select(.name == $name) | .value][0] // ""
      ' <<<"${revision_json}" 2>/dev/null || true
    }
    previous_version="$(revision_env DEPLOYED_POLICYENGINE_VERSION)"
    previous_since="$(revision_env POLICYENGINE_VERSION_LIVE_SINCE)"
    if [[ "${previous_version}" == "${version}" ]]; then
      live_since="${previous_since}"
    elif [[ -z "${previous_version}" ]]; then
      # A revision from before versions were recorded may already serve this
      # version, so its start is unknown.
      live_since=""
    fi
  else
    echo "Could not read ${previous}; when .py ${version} went live is unknown" >&2
    live_since=""
  fi
fi

printf 'DEPLOYED_POLICYENGINE_VERSION=%s\nPOLICYENGINE_VERSION_LIVE_SINCE=%s\n' \
  "${version}" "${live_since}"
