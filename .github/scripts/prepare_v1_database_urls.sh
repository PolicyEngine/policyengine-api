#!/usr/bin/env bash

set -euo pipefail

POLICYENGINE_DB_READONLY_PASSWORD="$(
  gcloud secrets versions access latest \
    --secret policyengine-api-prod-db-readonly-password \
    --project policyengine-api
)"
POLICYENGINE_DB_MIGRATION_PASSWORD="$(
  gcloud secrets versions access latest \
    --secret policyengine-api-prod-db-migration-password \
    --project policyengine-api
)"
export POLICYENGINE_DB_READONLY_PASSWORD POLICYENGINE_DB_MIGRATION_PASSWORD

python scripts/write_v1_database_urls.py
