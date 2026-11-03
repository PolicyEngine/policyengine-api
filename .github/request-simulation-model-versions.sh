#!/usr/bin/env bash

set -euo pipefail

# Simulation gateway version check script.
# Verifies that the PolicyEngine .py bundle the Public API installs is the latest
# one the selected simulation gateway has published, and that the gateway routes
# it, before a pull request merges or a deployment proceeds. The Public API's
# requests name their .py version, so the gateway's US and UK routes are not
# compared.

source .github/scripts/simulation_entrypoint_env.sh

GATEWAY_URL="$(
    simulation_entrypoint_selected_url "${SIM_ENTRYPOINT:-}"
)"

usage() {
    echo "Usage: $0 -py <policyengine_version> [--check-installed-spm]"
    echo ""
    echo "Required flags:"
    echo "  -py, --policyengine  policyengine_version  PolicyEngine .py bundle version"
    echo ""
    echo "Optional checks:"
    echo "  --check-installed-spm  Compare the installed bundle with worker capability"
    exit 1
}

POLICYENGINE_VERSION=""
CHECK_INSTALLED_SPM=0

while [ $# -gt 0 ]; do
    case "$1" in
        -py|--policyengine)
            POLICYENGINE_VERSION="$2"
            shift 2
            ;;
        --check-installed-spm)
            CHECK_INSTALLED_SPM=1
            shift
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

if [ -z "$POLICYENGINE_VERSION" ]; then
    echo "Error: -py/--policyengine version is required"
    usage
fi

echo "Checking selected simulation API versions..."
echo "  Gateway: $GATEWAY_URL"
echo "  Expected PolicyEngine .py bundle: $POLICYENGINE_VERSION"
echo ""

VERSIONS_RESPONSE=$(curl --fail --silent --show-error --connect-timeout 10 --max-time 60 "${GATEWAY_URL}/versions")

if [ -z "$VERSIONS_RESPONSE" ]; then
    echo "ERROR: Failed to fetch versions from gateway"
    exit 1
fi

BUNDLE_APP=$(echo "$VERSIONS_RESPONSE" | jq -r --arg v "$POLICYENGINE_VERSION" '.policyengine[$v] // empty')
if [ -z "$BUNDLE_APP" ]; then
    echo "ERROR: PolicyEngine .py bundle $POLICYENGINE_VERSION is NOT deployed in the simulation API"
    echo "Available PolicyEngine versions:"
    echo "$VERSIONS_RESPONSE" | jq -r '.policyengine | keys[]'
    exit 1
fi
echo "PolicyEngine .py bundle $POLICYENGINE_VERSION is deployed (app: $BUNDLE_APP)"

LATEST_POLICYENGINE_VERSION=$(echo "$VERSIONS_RESPONSE" | jq -r '.policyengine.latest // empty')
if [ -z "$LATEST_POLICYENGINE_VERSION" ]; then
    echo "ERROR: The simulation API reports no latest PolicyEngine .py bundle"
    exit 1
fi
if [ "$LATEST_POLICYENGINE_VERSION" != "$POLICYENGINE_VERSION" ]; then
    echo "ERROR: The Public API is on PolicyEngine .py $POLICYENGINE_VERSION, but the simulation API's latest is $LATEST_POLICYENGINE_VERSION"
    echo "Update the Public API's PolicyEngine bundle to $LATEST_POLICYENGINE_VERSION before deploying"
    exit 1
fi
echo "PolicyEngine .py bundle $POLICYENGINE_VERSION is the simulation API's latest"

if [ "$CHECK_INSTALLED_SPM" = "1" ]; then
    printf '%s' "$VERSIONS_RESPONSE" \
        | uv run --frozen python -m policyengine_api.worker_spm_release "$POLICYENGINE_VERSION"
fi

echo ""
echo "SUCCESS: PolicyEngine bundle route is deployed and ready"
exit 0
