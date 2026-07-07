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
#   2. DELETEs stopped versions beyond the retention window: keeps the newest
#      KEEP_STOPPED_PROD prod-* and KEEP_STOPPED_STAGING staging-* stopped
#      versions, and deletes every other stopped version (older prod, older
#      staging, and legacy timestamp-named versions), to stay under App Engine's
#      210-versions-per-service limit. Prod is kept deeper because only prod
#      versions are meaningful rollback targets.
#   3. DELETEs the Artifact Registry image for each deleted version so the
#      `gae-flexible` repo stays in lockstep with the retained versions (App
#      Engine Flex builds one image per version — `<service>.<version-id>` — and
#      nothing else prunes them, so the repo grows without bound). Best-effort
#      per image; set CLEANUP_APP_ENGINE_IMAGES=0 to skip.
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
KEEP_STOPPED_PROD="${KEEP_STOPPED_PROD:-10}"
KEEP_STOPPED_STAGING="${KEEP_STOPPED_STAGING:-3}"
DRY_RUN="${DRY_RUN:-0}"

# Delete each deleted version's App Engine Flex image from Artifact Registry so
# the image repo does not grow one image per version forever.
CLEANUP_APP_ENGINE_IMAGES="${CLEANUP_APP_ENGINE_IMAGES:-1}"
AR_LOCATION="${AR_LOCATION:-us-central1}"
AR_IMAGE_PROJECT="${AR_IMAGE_PROJECT:-${APP_ENGINE_PROJECT:-policyengine-api}}"
AR_IMAGE_REPO="${AR_IMAGE_REPO:-gae-flexible}"

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

# Fail safe: if there are SERVING versions but none report traffic, we cannot
# identify the live service. Refuse to stop anything rather than risk
# deactivating production (e.g. if the traffic query returns nothing). The
# delete step never runs either, since we exit here.
if [[ "${#serving_all[@]}" -gt 0 && "${#serving_traffic[@]}" -eq 0 ]]; then
  echo "ERROR: ${#serving_all[@]} SERVING version(s) but none are receiving traffic;" >&2
  echo "refusing to stop versions (cannot identify the live service). Aborting." >&2
  exit 1
fi

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

# Delete stopped versions beyond the retention window (version-quota hygiene).
# Keep the newest KEEP_STOPPED_PROD stopped prod-* versions (cold rollback
# targets) and the newest KEEP_STOPPED_STAGING stopped staging-* versions; delete
# everything else stopped — older prod, older staging, and legacy timestamp-named
# versions. Serving/warm versions are SERVING, so never appear in this set.
stopped_all=()
while IFS= read -r v; do
  [[ -n "${v}" ]] && stopped_all+=("${v}")
done < <(read_versions "version.servingStatus=STOPPED")

# Newest KEEP_STOPPED_PROD stopped prod-* versions to keep.
keep_stopped_prod=()
while IFS= read -r v; do
  [[ -n "${v}" ]] && keep_stopped_prod+=("${v}")
done < <(printf '%s\n' "${stopped_all[@]:-}" | grep '^prod-' | head -n "${KEEP_STOPPED_PROD}")

# Newest KEEP_STOPPED_STAGING stopped staging-* versions to keep.
keep_stopped_staging=()
while IFS= read -r v; do
  [[ -n "${v}" ]] && keep_stopped_staging+=("${v}")
done < <(printf '%s\n' "${stopped_all[@]:-}" | grep '^staging-' | head -n "${KEEP_STOPPED_STAGING}")

keep_stopped=("${keep_stopped_prod[@]:-}" "${keep_stopped_staging[@]:-}")

to_delete=()
for v in "${stopped_all[@]:-}"; do
  [[ -z "${v}" ]] && continue
  contains "${v}" "${keep_stopped[@]:-}" && continue
  to_delete+=("${v}")
done

echo "Stopped versions:                ${#stopped_all[@]}"
echo "Keeping stopped prod (${#keep_stopped_prod[@]}):          ${keep_stopped_prod[*]:-<none>}"
echo "Keeping stopped staging (${#keep_stopped_staging[@]}):       ${keep_stopped_staging[*]:-<none>}"
echo "Deleting (${#to_delete[@]}):                     ${to_delete[*]:-<none>}"

if [[ "${#to_delete[@]}" -gt 0 ]]; then
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[dry-run] would delete ${#to_delete[@]} version(s)"
  else
    gcloud app versions delete "${to_delete[@]}" "${common_args[@]}" --quiet
  fi
fi

# Delete each deleted version's App Engine Flex image so the image repo stays in
# lockstep with the retained versions. Best-effort per image: a version may
# predate this repo (older images live in the legacy us.gcr.io) or its image may
# already be gone, so individual misses are ignored.
if [[ "${CLEANUP_APP_ENGINE_IMAGES}" == "1" && "${#to_delete[@]}" -gt 0 ]]; then
  image_repo="${AR_LOCATION}-docker.pkg.dev/${AR_IMAGE_PROJECT}/${AR_IMAGE_REPO}"
  img_done=0
  for v in "${to_delete[@]}"; do
    [[ -z "${v}" ]] && continue
    image="${image_repo}/${APP_ENGINE_SERVICE}.${v}"
    if [[ "${DRY_RUN}" == "1" ]]; then
      echo "[dry-run] would delete image ${image}"
    elif gcloud artifacts docker images delete "${image}" --delete-tags --quiet \
      >/dev/null 2>&1; then
      img_done=$((img_done + 1))
    fi
  done
  [[ "${DRY_RUN}" == "1" ]] || echo "Deleted ${img_done}/${#to_delete[@]} gae-flexible image(s)."
fi
