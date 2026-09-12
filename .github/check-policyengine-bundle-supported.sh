#!/usr/bin/env bash

set -euo pipefail

CHECK_ONLY_IF_CHANGED=0
BASE_REF=""
VERSION_GUARD_SCRIPT="${SIMULATION_VERSION_GUARD_SCRIPT:-.github/request-simulation-model-versions.sh}"

usage() {
    echo "Usage: $0 [--if-changed-from-base <base_ref>]"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --if-changed-from-base)
            CHECK_ONLY_IF_CHANGED=1
            BASE_REF="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Error: Unknown option $1"
            usage
            ;;
    esac
done

extract_policyengine_version() {
    sed -n 's/.*policyengine\[models\]==\([0-9.][0-9.]*\).*/\1/p' | head -n 1
}

extract_calculator_version() {
    sed -n 's/.*spm-calculator==\([0-9.][0-9.]*\).*/\1/p' | head -n 1
}

current_version="$(extract_policyengine_version < pyproject.toml)"
current_calculator="$(extract_calculator_version < pyproject.toml)"
if [ -z "$current_version" ]; then
    echo "ERROR: policyengine[models] pin not found in pyproject.toml"
    exit 1
fi

if [ "$CHECK_ONLY_IF_CHANGED" = "1" ]; then
    if [ -z "$BASE_REF" ]; then
        echo "ERROR: --if-changed-from-base requires a base ref"
        exit 1
    fi

    git fetch --no-tags --depth=1 origin "$BASE_REF"
    base_version="$(
        git show "origin/${BASE_REF}:pyproject.toml" \
            | extract_policyengine_version \
            || true
    )"

    base_calculator="$(
        git show "origin/${BASE_REF}:pyproject.toml" \
            | extract_calculator_version \
            || true
    )"

    if [ "$current_version" = "$base_version" ] \
        && [ "$current_calculator" = "$base_calculator" ] \
        && git diff --quiet "origin/${BASE_REF}" -- \
            policyengine_api/spm.py policyengine_api/worker_spm.py \
            policyengine_api/worker_spm_release.py policyengine_api/constants.py \
            policyengine_api/country.py .github/check-policyengine-bundle-supported.sh \
            .github/request-simulation-model-versions.sh; then
        echo "Bundle/calculator pins and SPM integration are unchanged; skipping simulation API support check."
        exit 0
    fi
fi

bash "$VERSION_GUARD_SCRIPT" -py "$current_version" --check-installed-spm
