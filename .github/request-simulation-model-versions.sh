#!/usr/bin/env bash

set -e

# Modal Gateway version check script
# Verifies that the US and UK package versions used by API v1 are deployed
# in the Modal simulation API before allowing API v1 deployment to proceed.
#
# Usage: ./request-simulation-model-versions.sh -us <us_version> -uk <uk_version>

GATEWAY_URL="https://policyengine--policyengine-simulation-gateway-web-app.modal.run"

usage() {
    echo "Usage: $0 -us <us_version> -uk <uk_version>"
    echo ""
    echo "Required flags:"
    echo "  -us  us_version  - US package version (e.g., 1.459.0)"
    echo "  -uk  uk_version  - UK package version (e.g., 2.65.9)"
    exit 1
}

US_VERSION=""
UK_VERSION=""

while [ $# -gt 0 ]; do
    case "$1" in
        -us)
            US_VERSION="$2"
            shift 2
            ;;
        -uk)
            UK_VERSION="$2"
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

if [ -z "$US_VERSION" ] || [ -z "$UK_VERSION" ]; then
    echo "Error: Both -us and -uk versions are required"
    usage
fi

echo "Checking Modal simulation API versions..."
echo "  Gateway: $GATEWAY_URL"
echo "  Expected US version: $US_VERSION"
echo "  Expected UK version: $UK_VERSION"
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

# Check if UK version is deployed
UK_DEPLOYED=$(echo "$VERSIONS_RESPONSE" | jq -r --arg v "$UK_VERSION" '.uk[$v] // empty')
if [ -z "$UK_DEPLOYED" ]; then
    echo "ERROR: UK version $UK_VERSION is NOT deployed in Modal simulation API"
    echo "Available UK versions:"
    echo "$VERSIONS_RESPONSE" | jq -r '.uk | keys[]'
    exit 1
fi
echo "UK version $UK_VERSION is deployed (app: $UK_DEPLOYED)"

echo ""
echo "SUCCESS: Both US and UK versions are deployed and ready"
exit 0
