#!/usr/bin/env bash

set -euo pipefail

# Modal gateway version check script.
# Verifies that the PolicyEngine .py bundle used by API v1 is deployed in the
# simulation gateway before allowing API v1 deployment to proceed. US/UK
# versions are optional compatibility checks that should resolve to the same
# gateway app as the .py bundle route.

GATEWAY_URL="${SIMULATION_API_URL:-https://policyengine--policyengine-simulation-gateway-web-app.modal.run}"

usage() {
    echo "Usage: $0 -py <policyengine_version> [-us <us_version>] [-uk <uk_version>]"
    echo ""
    echo "Required flags:"
    echo "  -py, --policyengine  policyengine_version  PolicyEngine .py bundle version"
    echo ""
    echo "Optional compatibility checks:"
    echo "  -us  us_version  Expected bundled policyengine-us version"
    echo "  -uk  uk_version  Expected bundled policyengine-uk version"
    exit 1
}

POLICYENGINE_VERSION=""
US_VERSION=""
UK_VERSION=""

while [ $# -gt 0 ]; do
    case "$1" in
        -py|--policyengine)
            POLICYENGINE_VERSION="$2"
            shift 2
            ;;
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

if [ -z "$POLICYENGINE_VERSION" ]; then
    echo "Error: -py/--policyengine version is required"
    usage
fi

echo "Checking Modal simulation API versions..."
echo "  Gateway: $GATEWAY_URL"
echo "  Expected PolicyEngine .py bundle: $POLICYENGINE_VERSION"
if [ -n "$US_VERSION" ]; then
    echo "  Expected policyengine-us: $US_VERSION"
fi
if [ -n "$UK_VERSION" ]; then
    echo "  Expected policyengine-uk: $UK_VERSION"
fi
echo ""

VERSIONS_RESPONSE=$(curl -s "${GATEWAY_URL}/versions")

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

check_country_route() {
    local country="$1"
    local version="$2"
    local app

    if [ -z "$version" ]; then
        return
    fi

    app=$(echo "$VERSIONS_RESPONSE" | jq -r --arg country "$country" --arg v "$version" '.[$country][$v] // empty')
    if [ -z "$app" ]; then
        echo "ERROR: ${country} version ${version} is NOT deployed in the simulation API"
        echo "Available ${country} versions:"
        echo "$VERSIONS_RESPONSE" | jq -r --arg country "$country" '.[$country] | keys[]'
        exit 1
    fi

    if [ "$app" != "$BUNDLE_APP" ]; then
        echo "ERROR: ${country} version ${version} resolves to ${app}, not bundle app ${BUNDLE_APP}"
        exit 1
    fi

    echo "${country} version ${version} resolves to the same app"
}

check_country_route "us" "$US_VERSION"
check_country_route "uk" "$UK_VERSION"

echo ""
echo "SUCCESS: PolicyEngine bundle route is deployed and ready"
exit 0
