#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/cloud_run_env.sh
cloud_run_set_defaults

# --provenance=false makes the push a single image manifest. Docker 29 (the
# ubuntu-26.04 runner's) stores images in containerd, which keeps BuildKit's
# default provenance attestation, so without it the push is an image index
# that references the image manifest and an attestation manifest. Cloud Run
# needs only the image, and three manifests for each release would make
# cleanup_cloud_run_images.sh delete and keep more than it needs to.
docker_build_command=(
  docker build
  --platform "${CLOUD_RUN_IMAGE_PLATFORM}"
  --provenance=false
  -f gcp/cloud_run/Dockerfile
  -t "${CLOUD_RUN_IMAGE_URI}"
  .
)

if [[ "${CLOUD_RUN_DRY_RUN:-0}" == "1" ]]; then
  cloud_run_run gcloud artifacts repositories describe "${CLOUD_RUN_ARTIFACT_REPOSITORY}" --project "${CLOUD_RUN_PROJECT}" --location "${CLOUD_RUN_REGION}"
  cloud_run_run gcloud auth configure-docker "${CLOUD_RUN_REGION}-docker.pkg.dev" --quiet
  cloud_run_run "${docker_build_command[@]}"
  cloud_run_run docker push "${CLOUD_RUN_IMAGE_URI}"
  exit 0
fi

if ! gcloud artifacts repositories describe "${CLOUD_RUN_ARTIFACT_REPOSITORY}" \
  --project "${CLOUD_RUN_PROJECT}" \
  --location "${CLOUD_RUN_REGION}" >/dev/null 2>&1; then
  cat >&2 <<EOF
Missing Artifact Registry repository '${CLOUD_RUN_ARTIFACT_REPOSITORY}' in ${CLOUD_RUN_PROJECT}/${CLOUD_RUN_REGION}.
Provision the repository once before running Cloud Run deploys.
EOF
  exit 1
fi

gcloud auth configure-docker "${CLOUD_RUN_REGION}-docker.pkg.dev" --quiet
"${docker_build_command[@]}"
docker push "${CLOUD_RUN_IMAGE_URI}"
