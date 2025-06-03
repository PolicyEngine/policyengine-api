#! /usr/bin/env bash

set -e

# Google Cloud Workflow execution script
# Usage: ./wait_for_country_versions.sh -b <bucket_name> -us <us_version> -uk <uk_version> [-t timeout] [-i interval]

usage() {
    echo "Usage: $0 -b <bucket_name> -us <us_version> -uk <uk_version> [-t timeout] [-i interval]"
    echo ""
    echo "Required flags:"
    echo "  -b  bucket_name      - GCS bucket name"
    echo "  -us  us_version       - US package version"
    echo "  -uk  uk_version       - UK package version"
    echo ""
    echo "Optional flags:"
    echo "  -t  timeout_seconds  - Maximum wait time in seconds (default: 300)"
    echo "  -i  check_interval   - Check interval in seconds (default: 10)"
    echo "  -h  help            - Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 -b my-bucket -us v1.2.3 -uk v1.2.4"
    echo "  $0 -b my-bucket -us v1.2.3 -uk v1.2.4 -t 600 -i 15"
    exit 1
}

# Initialize variables
BUCKET_NAME=""
US_VERSION=""
UK_VERSION=""
TIMEOUT_SECONDS="300"
CHECK_INTERVAL="10"

# Parse command line arguments
while [ $# -gt 0 ]; do
    case "$1" in
        -b)
            if [ -z "$2" ]; then
                echo "Error: -b requires a bucket name"
                exit 1
            fi
            BUCKET_NAME="$2"
            shift 2
            ;;
        -us)
            if [ -z "$2" ]; then
                echo "Error: -us requires a US version"
                exit 1
            fi
            US_VERSION="$2"
            shift 2
            ;;
        -uk)
            if [ -z "$2" ]; then
                echo "Error: -uk requires a UK version"
                exit 1
            fi
            UK_VERSION="$2"
            shift 2
            ;;
        -t)
            if [ -z "$2" ]; then
                echo "Error: -t requires a timeout value"
                exit 1
            fi
            TIMEOUT_SECONDS="$2"
            shift 2
            ;;
        -i)
            if [ -z "$2" ]; then
                echo "Error: -i requires an interval value"
                exit 1
            fi
            CHECK_INTERVAL="$2"
            shift 2
            ;;
        -h)
            usage
            ;;
        *)
            echo "Error: Unknown option $1"
            usage
            ;;
    esac
done

# Validate required arguments
if [ -z "$BUCKET_NAME" ] || [ -z "$US_VERSION" ] || [ -z "$UK_VERSION" ]; then
    echo "Error: Missing required arguments"
    echo "bucket_name (-b), us_version (-us), and uk_version (-uk) are required"
    usage
fi

# Validate numeric arguments
if ! [[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || ! [[ "$CHECK_INTERVAL" =~ ^[0-9]+$ ]]; then
    echo "Error: timeout_seconds and check_interval must be positive integers"
    exit 1
fi

# Configuration
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
WORKFLOW_LOCATION="${WORKFLOW_LOCATION:-us-central1}"
WORKFLOW_NAME="wait-for-country-packages"

if [ -z "$PROJECT_ID" ]; then
    echo "Error: Could not determine project ID. Set GOOGLE_CLOUD_PROJECT environment variable."
    exit 1
fi

echo "Starting workflow execution..."
echo "Project: $PROJECT_ID"
echo "Location: $WORKFLOW_LOCATION"
echo "Workflow: $WORKFLOW_NAME"
echo "Bucket: $BUCKET_NAME"
echo "US Version: $US_VERSION"
echo "UK Version: $UK_VERSION"
echo "Timeout: ${TIMEOUT_SECONDS}s"
echo "Check Interval: ${CHECK_INTERVAL}s"

# Build input JSON
INPUT_JSON=$(cat <<EOF
{
  "bucket_name": "$BUCKET_NAME",
  "us_country_package_version": "$US_VERSION",
  "uk_country_package_version": "$UK_VERSION",
  "timeout_seconds": $TIMEOUT_SECONDS,
  "check_interval": $CHECK_INTERVAL
}
EOF
)

echo "Input: $INPUT_JSON"

# Execute workflow
echo "Executing workflow..."
EXECUTION_RESULT=$(gcloud workflows execute "$WORKFLOW_NAME" \
    --location="$WORKFLOW_LOCATION" \
    --data="$INPUT_JSON" \
    --format="json")

# Extract execution name
EXECUTION_NAME=$(echo "$EXECUTION_RESULT" | jq -r '.name')

if [ -z "$EXECUTION_NAME" ] || [ "$EXECUTION_NAME" = "null" ]; then
    echo "Failed to start workflow execution"
    echo "$EXECUTION_RESULT"
    exit 1
fi

echo "Execution started: $EXECUTION_NAME"

# Monitor execution state
START_TIME=$(date +%s)
echo "Monitoring execution state..."

while true; do
    # Get current execution state
    EXECUTION_STATUS=$(gcloud workflows executions wait "$EXECUTION_NAME" \
        --location="$WORKFLOW_LOCATION" \
        --format="json")
    
    STATE=$(echo "$EXECUTION_STATUS" | jq -r '.state')
    
    echo "Current state: $STATE"
    
    # Check if execution is complete
    if [ "$STATE" = "SUCCEEDED" ]; then
        echo "SUCCESS: Workflow completed successfully"
        RESULT=$(echo "$EXECUTION_STATUS" | jq -r '.result // empty')
        if [ -n "$RESULT" ] && [ "$RESULT" != "null" ]; then
            echo "Result: $RESULT"
        fi
        exit 0
    elif [ "$STATE" = "FAILED" ]; then
        echo "FAILED: Workflow execution failed"
        ERROR=$(echo "$EXECUTION_STATUS" | jq -r '.error // empty')
        if [ -n "$ERROR" ] && [ "$ERROR" != "null" ]; then
            echo "Error: $ERROR"
        fi
        exit 1
    elif [ "$STATE" = "CANCELLED" ]; then
        echo "CANCELLED: Workflow execution was cancelled"
        exit 1
    fi
    
    # Check monitoring timeout
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    
    if [ $ELAPSED -ge $((TIMEOUT_SECONDS + 60)) ]; then
        echo "TIMEOUT: Monitoring timeout exceeded"
        echo "Workflow may still be running. Check Google Cloud Console for status."
        exit 1
    fi
    
    # Wait before next check
    sleep "$CHECK_INTERVAL"
done