#!/usr/bin/env bash

set -euo pipefail

VERSION_GUARD_SCRIPT="${SIMULATION_VERSION_GUARD_SCRIPT:-.github/request-simulation-model-versions.sh}"

if [ $# -ne 0 ]; then
    echo "Usage: $0"
    exit 1
fi

extract_policyengine_version() {
    sed -n 's/.*policyengine\[models\]==\([0-9.][0-9.]*\).*/\1/p' | head -n 1
}

current_version="$(extract_policyengine_version < pyproject.toml)"
if [ -z "$current_version" ]; then
    echo "ERROR: policyengine[models] pin not found in pyproject.toml"
    exit 1
fi

bash "$VERSION_GUARD_SCRIPT" -py "$current_version" --check-installed-spm
