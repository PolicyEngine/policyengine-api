#!/usr/bin/env bash

# Write the image tag and revision tag for a Cloud Run deploy to GITHUB_OUTPUT.
#
# Usage: compute_cloud_run_metadata.sh <revision-tag-prefix>
# Reads GITHUB_SHA and GITHUB_RUN_NUMBER, which GitHub Actions sets for every
# job. Keep the prefix short: Cloud Run caps tag + service name at 46 combined
# chars.

set -euo pipefail

prefix="${1:?revision tag prefix is required}"
sha="${GITHUB_SHA:?GITHUB_SHA is required}"
run_number="${GITHUB_RUN_NUMBER:?GITHUB_RUN_NUMBER is required}"
output="${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

{
  echo "image_tag=${sha}"
  echo "revision_tag=${prefix}-${run_number}-${sha::7}"
} >> "${output}"
