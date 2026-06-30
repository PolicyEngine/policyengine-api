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

current_version="$(extract_policyengine_version < pyproject.toml)"
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

    if [ "$current_version" = "$base_version" ]; then
        echo "PolicyEngine .py bundle pin is unchanged; skipping simulation API support check."
        exit 0
    fi
fi

bash "$VERSION_GUARD_SCRIPT" -py "$current_version"
