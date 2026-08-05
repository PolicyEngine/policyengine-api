#!/usr/bin/env bash

set -euo pipefail

baseline_url="${1:?baseline stable URL is required}"
candidate_url="${2:?candidate URL is required}"
repetitions="${3:-5}"

results_dir="$(mktemp -d)"
trap 'rm -rf "${results_dir}"' EXIT

python scripts/capture_migration_baseline.py \
  --base-url "${baseline_url}" --repetitions 1 >/dev/null
python scripts/capture_migration_baseline.py \
  --base-url "${candidate_url}" --repetitions 1 >/dev/null
python scripts/capture_migration_baseline.py \
  --base-url "${baseline_url}" --repetitions "${repetitions}" \
  >"${results_dir}/baseline.json"
python scripts/capture_migration_baseline.py \
  --base-url "${candidate_url}" --repetitions "${repetitions}" \
  >"${results_dir}/candidate.json"
python scripts/compare_migration_baseline.py \
  "${results_dir}/baseline.json" "${results_dir}/candidate.json" \
  --error-rate-margin 0.001 --p95-ratio 1.20
