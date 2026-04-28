#!/usr/bin/env bash

set -euo pipefail

python gcp/export.py
cp gcp/policyengine_api/app.yaml .
cp gcp/policyengine_api/Dockerfile .
cp gcp/policyengine_api/start.sh .
