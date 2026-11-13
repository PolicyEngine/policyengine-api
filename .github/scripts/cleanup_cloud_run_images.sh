#!/usr/bin/env bash

# Keep only the Cloud Run images of the most recent releases in Artifact
# Registry.
#
# The Cloud Run deploy pushes a new image on every release and nothing prunes
# them, so the repo grows without bound. This keeps the images of the newest
# KEEP releases and deletes the manifests of older ones.
#
# A release is a tagged manifest: the staging deploy tags the image it pushes
# with the release commit. build_cloud_run_image.sh pushes one image manifest
# per release. Releases built on the ubuntu-26.04 runner before it turned off
# Docker's provenance attestation pushed three manifests instead: an image
# index (tagged) that references the image manifest and an attestation
# manifest (both untagged), all listed with the same upload time. Artifact
# Registry refuses to delete a manifest that an index still references, and
# deleting an index leaves the manifests it references in place. So:
#
#   1. The newest KEEP tagged manifests are the kept releases. Every older
#      tagged manifest is deleted first.
#   2. Then every untagged manifest uploaded before the oldest kept release is
#      deleted: the manifests that the indexes deleted in step 1, or by
#      earlier runs, referenced. Untagged manifests listed with the same
#      upload time as the oldest kept release, or a later one, are kept. That
#      keeps the manifests a kept index references when they are listed with
#      its upload time, as the releases built on ubuntu-26.04 were.
#   3. A deletion that Artifact Registry refuses because another manifest
#      still references the manifest is logged and not counted as a failure.
#      A manifest uploaded just before the kept index that references it is
#      refused like this on every run until that index is deleted. A manifest
#      whose untagged index (left when a tag is pushed again) is deleted later
#      in the same run is deleted by the next run.
#
# Note: deleting an image that an older Cloud Run *revision* still references
# stops that revision from starting again. Cloud Run here is the non-primary
# migration candidate, so losing rollback to revisions older than KEEP
# releases is acceptable; KEEP=15 leaves a generous window.
#
# Manifests are sorted in-script (by upload time) rather than trusting gcloud's
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

if [[ ! "${KEEP}" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::KEEP must be a whole number of releases, 1 or more; got '${KEEP}'."
  exit 1
fi

image_repo="${AR_LOCATION}-docker.pkg.dev/${AR_PROJECT}/${AR_REPO}"

# One row per manifest: upload time, image, digest, and tags (joined with ";",
# empty when the manifest is untagged). The listing is read into a variable
# first because bash ignores the exit status of a process substitution, so a
# failed listing would otherwise look like 0 images.
if ! listing="$(
  gcloud artifacts docker images list "${image_repo}" --include-tags \
    --format="value[separator='|'](createTime,package,version,tags)"
)"; then
  echo "::error::Could not list images in ${image_repo}."
  exit 1
fi

# Newest first: ISO timestamps sort chronologically. LC_ALL=C compares bytes,
# so manifests with the same upload time always sort in the same order.
refs=()
upload_times=()
tagged_flags=()
while IFS='|' read -r upload_time package digest tags; do
  if [[ -n "${digest}" ]]; then
    refs+=("${package}@${digest}")
    upload_times+=("${upload_time}")
    if [[ -n "${tags}" ]]; then
      tagged_flags+=("tagged")
    else
      tagged_flags+=("untagged")
    fi
  fi
done < <(printf '%s\n' "${listing}" | LC_ALL=C sort -r)
manifest_count="${#refs[@]}"

# The oldest kept release is the KEEP-th tagged manifest, or the last one when
# there are fewer releases than that.
release_count=0
oldest_kept_position=-1
position=0
while [[ "${position}" -lt "${manifest_count}" ]]; do
  if [[ "${tagged_flags[position]}" == "tagged" ]]; then
    release_count=$((release_count + 1))
    if [[ "${release_count}" -le "${KEEP}" ]]; then
      oldest_kept_position="${position}"
    fi
  fi
  position=$((position + 1))
done

# Everything listed after the oldest kept release is no newer than it. Its
# tagged manifests are older releases; its untagged manifests with an earlier
# upload time belong to no kept release.
old_release_refs=()
untagged_refs=()
if [[ "${oldest_kept_position}" -ge 0 ]]; then
  oldest_kept_upload_time="${upload_times[oldest_kept_position]}"
  position=$((oldest_kept_position + 1))
  while [[ "${position}" -lt "${manifest_count}" ]]; do
    if [[ "${tagged_flags[position]}" == "tagged" ]]; then
      old_release_refs+=("${refs[position]}")
    elif [[ "${upload_times[position]}" != "${oldest_kept_upload_time}" ]]; then
      untagged_refs+=("${refs[position]}")
    fi
    position=$((position + 1))
  done
fi
delete_count=$((${#old_release_refs[@]} + ${#untagged_refs[@]}))

echo "Repo:      ${image_repo}"
echo "Manifests: ${manifest_count} (${release_count} tagged release(s); keeping newest ${KEEP})"
echo "Deleting:  ${delete_count} (${#old_release_refs[@]} tagged, ${#untagged_refs[@]} untagged uploaded before the oldest kept release)"
if [[ "${manifest_count}" -gt 0 && "${release_count}" -eq 0 ]]; then
  echo "::warning::No tagged image in ${image_repo}, so no release to keep; deleting nothing."
fi

deleted=0
failed=0
still_referenced=0
# Tagged manifests first: deleting an old release's index lets the manifests
# it references be deleted after it.
for ref in "${old_release_refs[@]:-}" "${untagged_refs[@]:-}"; do
  [[ -z "${ref}" ]] && continue
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[dry-run] would delete ${ref}"
  elif output="$(gcloud artifacts docker images delete "${ref}" --delete-tags \
    --quiet 2>&1)"; then
    deleted=$((deleted + 1))
  elif [[ "${output}" == *"referenced by parent manifests"* ]]; then
    still_referenced=$((still_referenced + 1))
    echo "Kept ${ref}: another manifest still references it."
  else
    failed=$((failed + 1))
    echo "Failed to delete ${ref}:"
    while IFS= read -r error_line; do
      echo "  ${error_line}"
    done <<< "${output}"
  fi
done
if [[ "${DRY_RUN}" != "1" ]]; then
  if [[ "${still_referenced}" -gt 0 ]]; then
    echo "Deleted ${deleted}/${delete_count} manifest(s); kept ${still_referenced} that another manifest still references."
  else
    echo "Deleted ${deleted}/${delete_count} manifest(s)."
  fi
fi
if [[ "${failed}" -gt 0 ]]; then
  echo "::error::Failed to delete ${failed}/${delete_count} manifest(s); the gcloud errors are above."
  exit 1
fi
