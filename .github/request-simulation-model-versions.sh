#!/usr/bin/env bash

set -e

# Modal Gateway version check script
# Verifies that the US package version used by API v1 is deployed
# in the Modal simulation API before allowing API v1 deployment to proceed.
#
# NOTE: We explicitly do NOT check for UK versions here. The UK package
# (policyengine-uk) does not support the older Python versions that API v1
# runs on, so the UK version deployed to Modal may not match the version
# pinned in API v1's requirements.
#
# Usage: ./request-simulation-model-versions.sh -us <us_version>

GATEWAY_URL="https://policyengine--policyengine-simulation-gateway-web-app.modal.run"

usage() {
    echo "Usage: $0 -us <us_version>"
    echo ""
    echo "Required flags:"
    echo "  -us  us_version  - US package version (e.g., 1.459.0)"
    exit 1
}

US_VERSION=""

while [ $# -gt 0 ]; do
    case "$1" in
        -us)
            US_VERSION="$2"
            shift 2
            ;;
        -uk)
            # Accept but ignore UK version flag for backwards compatibility
            echo "Note: UK version check is disabled (see script comments)"
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

if [ -z "$US_VERSION" ]; then
    echo "Error: -us version is required"
    usage
fi

echo "Checking Modal simulation API versions..."
echo "  Gateway: $GATEWAY_URL"
echo "  Expected US version: $US_VERSION"
echo ""

# Query the gateway for deployed versions
VERSIONS_RESPONSE=$(curl -s "${GATEWAY_URL}/versions")

if [ -z "$VERSIONS_RESPONSE" ]; then
    echo "ERROR: Failed to fetch versions from gateway"
    exit 1
fi

# Check if US version is deployed
US_DEPLOYED=$(echo "$VERSIONS_RESPONSE" | jq -r --arg v "$US_VERSION" '.us[$v] // empty')
if [ -z "$US_DEPLOYED" ]; then
    echo "ERROR: US version $US_VERSION is NOT deployed in Modal simulation API"
    echo "Available US versions:"
    echo "$VERSIONS_RESPONSE" | jq -r '.us | keys[]'
    exit 1
fi
echo "US version $US_VERSION is deployed (app: $US_DEPLOYED)"

echo ""
echo "SUCCESS: US version is deployed and ready"
exit 0
