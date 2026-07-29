#!/usr/bin/env bash

set -euo pipefail

source .github/scripts/simulation_entrypoint_env.sh
simulation_entrypoint_load_git_selection

python gcp/export.py
cp gcp/policyengine_api/app.yaml .
cp gcp/policyengine_api/Dockerfile .
cp gcp/policyengine_api/start.sh .
