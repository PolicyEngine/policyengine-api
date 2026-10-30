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
#
# The target repo (region/project/repository) comes from cloud_run_env.sh — the
# same config the deploy scripts source — so this can never prune a different
# repo than the pipeline actually pushes to.
#
# A failed listing or deletion fails the script, and each failed deletion is
# logged with gcloud's error. Deleting an image needs
# artifactregistry.versions.delete on the repo, and artifactregistry.tags.delete
# too when it is tagged; roles/artifactregistry.writer has neither.

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

KEEP="${KEEP:-15}"
DRY_RUN="${DRY_RUN:-0}"
AR_LOCATION="${AR_LOCATION:-${CLOUD_RUN_REGION}}"
AR_PROJECT="${AR_PROJECT:-${CLOUD_RUN_PROJECT}}"
AR_REPO="${AR_REPO:-${CLOUD_RUN_ARTIFACT_REPOSITORY}}"

image_repo="${AR_LOCATION}-docker.pkg.dev/${AR_PROJECT}/${AR_REPO}"

# Deletable refs (<image>@<digest>), newest first — sorted here by createTime
# (ISO timestamps sort chronologically), one row per image version. The listing
# is read into a variable first because bash ignores the exit status of a
# process substitution, so a failed listing would otherwise look like 0 images.
if ! listing="$(
  gcloud artifacts docker images list "${image_repo}" \
    --format="value[separator='|'](createTime,package,version)"
)"; then
  echo "::error::Could not list images in ${image_repo}."
  exit 1
fi
refs=()
while IFS='|' read -r _ctime pkg ver; do
  if [[ -n "${ver}" ]]; then
    refs+=("${pkg}@${ver}")
  fi
done < <(printf '%s\n' "${listing}" | sort -r)

total="${#refs[@]}"
to_delete=()
if [[ "${total}" -gt "${KEEP}" ]]; then
  to_delete=("${refs[@]:${KEEP}}")
fi

echo "Repo:      ${image_repo}"
echo "Images:    ${total} (keeping newest ${KEEP})"
echo "Deleting:  ${#to_delete[@]}"

deleted=0
failed=0
for ref in "${to_delete[@]:-}"; do
  [[ -z "${ref}" ]] && continue
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[dry-run] would delete ${ref}"
  elif output="$(gcloud artifacts docker images delete "${ref}" --delete-tags \
    --quiet 2>&1)"; then
    deleted=$((deleted + 1))
  else
    failed=$((failed + 1))
    echo "Failed to delete ${ref}:"
    while IFS= read -r error_line; do
      echo "  ${error_line}"
    done <<< "${output}"
  fi
done
if [[ "${DRY_RUN}" != "1" ]]; then
  echo "Deleted ${deleted}/${#to_delete[@]} image(s)."
fi
if [[ "${failed}" -gt 0 ]]; then
  echo "::error::Failed to delete ${failed}/${#to_delete[@]} image(s); the gcloud errors are above."
  exit 1
fi
