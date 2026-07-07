#!/usr/bin/env bash

# One-time purge of stale Artifact Registry storage in policyengine-api.
#
# The image repos accumulated ~628 GiB that is never cleaned up. This removes
# the dead legacy repos and prunes the live repos to their retention windows.
# INTERACTIVE: prints what it will do and asks before each destructive step.
# Safe to re-run (idempotent).
#
#   1. Pre-check: abort if any App Engine version's image lives in a repo we
#      are about to delete.
#   2. Delete dead repos wholesale: us.gcr.io, gcr.io, cloud-run-source-deploy.
#   3. Prune gae-flexible: delete images whose App Engine version no longer
#      exists (orphans left by already-deleted versions).
#   4. Prune the Cloud Run repo to the newest 15 (cleanup_cloud_run_images.sh).
#
# Usage: PROJECT=policyengine-api bash .github/scripts/purge_stale_artifact_registry.sh
#
# Written for bash 3.2.

set -euo pipefail

PROJECT="${PROJECT:-policyengine-api}"
LOCATION="${LOCATION:-us-central1}"
SERVICE="${SERVICE:-default}"
GAE_REPO="gae-flexible"
DEAD_REPOS=("us.gcr.io" "gcr.io" "cloud-run-source-deploy")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

confirm() {
  local reply
  read -r -p "$1 (y/N) " reply
  [[ "${reply}" =~ ^[Yy]$ ]]
}

echo "=== Purge stale Artifact Registry storage in ${PROJECT} ==="
echo ""

# --- 1. Pre-check: dead repos are not referenced by any live version ---------
echo "[1/4] Checking no App Engine version references the repos to be deleted..."
version_images="$(gcloud app versions list --project="${PROJECT}" --service="${SERVICE}" \
  --format="value(deployment.container.image)" 2>/dev/null || true)"
for repo in "${DEAD_REPOS[@]}"; do
  if printf '%s\n' "${version_images}" | grep -q "/${repo}/"; then
    echo "ABORT: an App Engine version still references '${repo}'. Not safe." >&2
    exit 1
  fi
done
echo "      OK — no live version references ${DEAD_REPOS[*]}."
echo ""

# --- 2. Delete the dead repos wholesale --------------------------------------
for repo in "${DEAD_REPOS[@]}"; do
  if ! gcloud artifacts repositories describe "${repo}" --location="${LOCATION}" \
    --project="${PROJECT}" >/dev/null 2>&1; then
    echo "[2/4] Repo '${repo}' not found (already gone) — skipping."
    continue
  fi
  size="$(gcloud artifacts repositories describe "${repo}" --location="${LOCATION}" \
    --project="${PROJECT}" --format="value(sizeBytes.size())" 2>/dev/null || echo '?')"
  echo "[2/4] Dead repo '${repo}' (${size})."
  if confirm "      Delete repository '${repo}' entirely?"; then
    gcloud artifacts repositories delete "${repo}" --location="${LOCATION}" \
      --project="${PROJECT}" --quiet
    echo "      deleted ${repo}."
  else
    echo "      skipped ${repo}."
  fi
done
echo ""

# --- 3. Prune gae-flexible orphans (images whose version is gone) ------------
echo "[3/4] Pruning ${GAE_REPO} images whose App Engine version no longer exists..."
existing_versions="$(gcloud app versions list --project="${PROJECT}" --service="${SERVICE}" \
  --format="value(id)" 2>/dev/null || true)"
orphans=()
while IFS= read -r pkg; do
  [[ -z "${pkg}" ]] && continue
  base="${pkg##*/}"                 # "<service>.<version-id>"
  [[ "${base}" == "${SERVICE}."* ]] || continue
  vid="${base#"${SERVICE}."}"
  printf '%s\n' "${existing_versions}" | grep -qxF "${vid}" || orphans+=("${pkg}")
done < <(
  gcloud artifacts docker images list \
    "${LOCATION}-docker.pkg.dev/${PROJECT}/${GAE_REPO}" \
    --format="value(package)" 2>/dev/null | sort -u
)
echo "      ${#orphans[@]} orphaned image(s) (version deleted)."
if [[ "${#orphans[@]}" -gt 0 ]] && confirm "      Delete ${#orphans[@]} orphaned ${GAE_REPO} image(s)?"; then
  for pkg in "${orphans[@]}"; do
    if gcloud artifacts docker images delete "${pkg}" --delete-tags --quiet >/dev/null 2>&1; then
      echo "      deleted ${pkg##*/}"
    else
      echo "      skip ${pkg##*/}"
    fi
  done
fi
echo ""

# --- 4. Prune the Cloud Run repo to the newest 15 ----------------------------
echo "[4/4] Pruning the Cloud Run image repo to the newest 15..."
if confirm "      Run cleanup_cloud_run_images.sh (keep 15)?"; then
  CLOUD_RUN_PROJECT="${PROJECT}" bash "${SCRIPT_DIR}/cleanup_cloud_run_images.sh"
fi
echo ""
echo "Done."
