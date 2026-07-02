#!/usr/bin/env bash

# Stops zero-traffic App Engine versions beyond a retention window.
#
# Versions on the flexible environment keep their VMs running — and billing —
# 24/7 while in SERVING state, even at a 0% traffic split. Every deploy leaves
# one behind (staging and prod), so without cleanup the fleet grows by two
# 4vCPU/24GB VMs (~$278/month each) per release: by July 2026 this had
# accumulated 41 zero-traffic versions costing roughly $11k/month.

set -euo pipefail

APP_ENGINE_SERVICE="${APP_ENGINE_SERVICE:-default}"
KEEP_PER_PREFIX="${KEEP_PER_PREFIX:-2}"

project_args=()
if [[ -n "${APP_ENGINE_PROJECT:-}" ]]; then
  project_args+=("--project=${APP_ENGINE_PROJECT}")
fi

# Versions currently receiving traffic are never stopped, regardless of age.
live_versions="$(gcloud app versions list \
  --service="${APP_ENGINE_SERVICE}" \
  --hide-no-traffic \
  --format="value(version.id)" \
  ${project_args[@]+"${project_args[@]}"})"

for prefix in prod staging; do
  serving="$(gcloud app versions list \
    --service="${APP_ENGINE_SERVICE}" \
    --filter="version.servingStatus=SERVING AND version.id:${prefix}-*" \
    --sort-by="~version.createTime" \
    --format="value(version.id)" \
    ${project_args[@]+"${project_args[@]}"})"

  stale="$(tail -n +"$((KEEP_PER_PREFIX + 1))" <<<"${serving}")"

  for version in ${stale}; do
    if grep -qx "${version}" <<<"${live_versions}"; then
      echo "Skipping ${version}: currently receiving traffic"
      continue
    fi
    echo "Stopping zero-traffic version ${version}"
    gcloud app versions stop --quiet \
      --service="${APP_ENGINE_SERVICE}" \
      "${version}" \
      ${project_args[@]+"${project_args[@]}"}
  done
done
