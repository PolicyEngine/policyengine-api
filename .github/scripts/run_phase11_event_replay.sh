#!/usr/bin/env bash

set -euo pipefail

: "${PHASE11_STATE_PATH:?PHASE11_STATE_PATH is required}"

legacy_household_id="$(jq -er '.pending_legacy_household_id' "${PHASE11_STATE_PATH}")"

bash .github/scripts/run_household_mirror_event_operator.sh \
  --environment staging \
  --country-id us \
  --legacy-household-id "${legacy_household_id}"
