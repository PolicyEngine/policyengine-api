#!/usr/bin/env bash

# Deactivate idle App Engine versions after a production promote.
#
# App Engine Flexible keeps at least one always-on VM for every SERVING version,
# regardless of traffic, so old versions left SERVING after a promote keep
# costing money even at 0 traffic (~$212/mo per 4 vCPU / 24 GB version). The
# deploy pipeline promotes traffic with set-traffic but never deactivates the
# versions it supersedes, so they pile up.
#
# This script, run after promote-production:
#   1. Keeps the version currently receiving traffic PLUS the newest
#      KEEP_WARM_PROD prod-* versions SERVING (a warm rollback window), and STOPs
#      every other SERVING version (older prod + any leftover staging).
#   2. DELETEs STOPPED versions beyond the newest KEEP_STOPPED, to stay under
#      App Engine's 210-versions-per-service limit.
#
# Stopping (not deleting) preserves rollback: a stopped version can be brought
# back with `gcloud app versions start <v>` then `gcloud app services set-traffic
# ${SERVICE} --splits=<v>=1`. The version currently serving traffic is never
# stopped or deleted.
#
# Set DRY_RUN=1 to print the plan without changing anything.
#
# Written to run on bash 3.2 (no mapfile / associative arrays) so it can be
# dry-run locally on macOS as well as in CI.

set -euo pipefail

APP_ENGINE_SERVICE="${APP_ENGINE_SERVICE:-default}"
KEEP_WARM_PROD="${KEEP_WARM_PROD:-2}"
KEEP_STOPPED="${KEEP_STOPPED:-20}"
DRY_RUN="${DRY_RUN:-0}"

common_args=("--service=${APP_ENGINE_SERVICE}")
if [[ -n "${APP_ENGINE_PROJECT:-}" ]]; then
  common_args+=("--project=${APP_ENGINE_PROJECT}")
fi

contains() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    [[ "${item}" == "${needle}" ]] && return 0
  done
  return 1
}

read_versions() {
  # Args: extra gcloud filter. Emits version ids newest-first, one per line.
  local filter="$1"
  gcloud app versions list "${common_args[@]}" \
    --filter="${filter}" \
    --sort-by="~version.createTime" \
    --format="value(id)"
}

# Versions currently receiving any traffic — never touched.
serving_traffic=()
while IFS= read -r v; do
  [[ -n "${v}" ]] && serving_traffic+=("${v}")
done < <(read_versions "version.servingStatus=SERVING AND traffic_split>0")

# All SERVING versions, newest first.
serving_all=()
while IFS= read -r v; do
  [[ -n "${v}" ]] && serving_all+=("${v}")
done < <(read_versions "version.servingStatus=SERVING")

# Newest KEEP_WARM_PROD prod-* versions to keep warm for instant rollback.
warm_prod=()
while IFS= read -r v; do
  [[ -n "${v}" ]] && warm_prod+=("${v}")
done < <(printf '%s\n' "${serving_all[@]:-}" | grep '^prod-' | head -n "${KEEP_WARM_PROD}")

# Keep set = traffic-serving versions + warm prod versions.
keep=("${serving_traffic[@]:-}" "${warm_prod[@]:-}")

# Stop every SERVING version not in the keep set.
to_stop=()
for v in "${serving_all[@]:-}"; do
  [[ -z "${v}" ]] && continue
  contains "${v}" "${keep[@]:-}" && continue
  to_stop+=("${v}")
done

echo "Service:                         ${APP_ENGINE_SERVICE}"
echo "Serving traffic (never touched): ${serving_traffic[*]:-<none>}"
echo "Keeping warm (rollback window):  ${warm_prod[*]:-<none>}"
echo "Stopping (${#to_stop[@]}):                     ${to_stop[*]:-<none>}"

if [[ "${#to_stop[@]}" -gt 0 ]]; then
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[dry-run] would stop ${#to_stop[@]} version(s)"
  else
    gcloud app versions stop "${to_stop[@]}" "${common_args[@]}" --quiet
  fi
fi

# Delete STOPPED versions beyond the newest KEEP_STOPPED (version-quota hygiene).
stopped_all=()
while IFS= read -r v; do
  [[ -n "${v}" ]] && stopped_all+=("${v}")
done < <(read_versions "version.servingStatus=STOPPED")

to_delete=()
if [[ "${#stopped_all[@]}" -gt "${KEEP_STOPPED}" ]]; then
  to_delete=("${stopped_all[@]:${KEEP_STOPPED}}")
fi

echo "Stopped versions:                ${#stopped_all[@]} (keeping newest ${KEEP_STOPPED})"
echo "Deleting (${#to_delete[@]}):                     ${to_delete[*]:-<none>}"

if [[ "${#to_delete[@]}" -gt 0 ]]; then
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[dry-run] would delete ${#to_delete[@]} version(s)"
  else
    gcloud app versions delete "${to_delete[@]}" "${common_args[@]}" --quiet
  fi
fi
