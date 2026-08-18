#!/usr/bin/env bash

set -euo pipefail

python3 gcp/export.py
cp gcp/policyengine_api/start.sh .
