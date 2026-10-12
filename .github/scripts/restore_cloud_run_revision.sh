#!/usr/bin/env bash

# Roll Cloud Run traffic back to the previous revision, then confirm it is
# healthy.
#
# Usage: restore_cloud_run_revision.sh <readiness-url>
# set_cloud_run_revision.sh reads CLOUD_RUN_TARGET_REVISION,
# CLOUD_RUN_EXPECTED_CURRENT_REVISION and CLOUD_RUN_SERVICE from the
# environment. CLOUD_RUN_SCRIPTS_DIR overrides where the two scripts are found
# (tests use it).

set -euo pipefail

readiness_url="${1:?readiness URL is required}"
scripts_dir="${CLOUD_RUN_SCRIPTS_DIR:-.github/scripts}"

bash "${scripts_dir}/set_cloud_run_revision.sh"
bash "${scripts_dir}/health_check.sh" "${readiness_url}"
