#!/usr/bin/env bash

# Keep only the most recent Cloud Run images in Artifact Registry.
#
# The Cloud Run deploy pushes a new image on every release and nothing prunes
# them, so the repo grows without bound. This keeps the newest KEEP image
# versions (by createTime) and deletes the rest.
#
# Note: deleting an image that an older Cloud Run *revision* still references
# stops that revision from starting again. Cloud Run here is the non-primary
# migration candidate, so losing rollback to revisions older than KEEP deploys
# is acceptable; KEEP=15 leaves a generous window.
#
# Images are sorted in-script (by createTime) rather than trusting gcloud's
# Artifact Registry `--sort-by`, which has proven unreliable. Set DRY_RUN=1 to
# print the plan without changing anything. Written for bash 3.2.

set -euo pipefail

KEEP="${KEEP:-15}"
DRY_RUN="${DRY_RUN:-0}"
AR_LOCATION="${AR_LOCATION:-us-central1}"
AR_PROJECT="${AR_PROJECT:-${CLOUD_RUN_PROJECT:-policyengine-api}}"
AR_REPO="${AR_REPO:-${CLOUD_RUN_ARTIFACT_REPOSITORY:-policyengine-api}}"

image_repo="${AR_LOCATION}-docker.pkg.dev/${AR_PROJECT}/${AR_REPO}"

# Deletable refs (<image>@<digest>), newest first — sorted here by createTime
# (ISO timestamps sort chronologically), one row per image version.
refs=()
while IFS='|' read -r _ctime pkg ver; do
  [[ -n "${ver}" ]] && refs+=("${pkg}@${ver}")
done < <(
  gcloud artifacts docker images list "${image_repo}" \
    --format="value[separator='|'](createTime,package,version)" \
    | sort -r
)

total="${#refs[@]}"
to_delete=()
if [[ "${total}" -gt "${KEEP}" ]]; then
  to_delete=("${refs[@]:${KEEP}}")
fi

echo "Repo:      ${image_repo}"
echo "Images:    ${total} (keeping newest ${KEEP})"
echo "Deleting:  ${#to_delete[@]}"

deleted=0
for ref in "${to_delete[@]:-}"; do
  [[ -z "${ref}" ]] && continue
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[dry-run] would delete ${ref}"
  elif gcloud artifacts docker images delete "${ref}" --delete-tags --quiet \
    >/dev/null 2>&1; then
    deleted=$((deleted + 1))
  fi
done
[[ "${DRY_RUN}" == "1" ]] || echo "Deleted ${deleted}/${#to_delete[@]} image(s)."
