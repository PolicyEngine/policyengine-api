#!/usr/bin/env bash

set -euo pipefail

required=(
  DEPLOYMENT_ENVIRONMENT
  ROUTE_IMPL_POLICY
  DB_READ_POLICY
  DB_WRITE_POLICY
  V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE
  V2_FAILURE_DATABASE_URL_SECRET_RESOURCE
  POLICYENGINE_DB_READONLY_PASSWORD_SECRET
)

for setting in "${required[@]}"; do
  if [[ -z "${!setting:-}" ]]; then
    printf '%s is required for the Phase 10 staging exercise\n' "${setting}" >&2
    exit 1
  fi
done

if [[ "${DEPLOYMENT_ENVIRONMENT}" != "staging" ]]; then
  echo "The Phase 10 live exercise may run only against staging." >&2
  exit 1
fi
if [[ "${ROUTE_IMPL_POLICY}" != "fastapi_native" ]]; then
  echo "ROUTE_IMPL_POLICY must be fastapi_native for the Phase 10 exercise." >&2
  exit 1
fi
if [[ "${DB_READ_POLICY}" != "cloud_sql" ]]; then
  echo "DB_READ_POLICY must remain cloud_sql for the Phase 10 exercise." >&2
  exit 1
fi
if [[ "${DB_WRITE_POLICY}" != "cloud_sql" ]]; then
  echo "The staging candidate must begin with DB_WRITE_POLICY=cloud_sql." >&2
  exit 1
fi
if [[ "${V2_FAILURE_DATABASE_URL_SECRET_RESOURCE}" == \
  "${V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE}" ]]; then
  echo "The controlled-failure database secret must differ from the valid staging secret." >&2
  exit 1
fi
if [[ "${V2_FAILURE_DATABASE_URL_SECRET_RESOURCE}" == \
  "${PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE:-}" ]]; then
  echo "The controlled-failure database secret must not identify production." >&2
  exit 1
fi

bash .github/scripts/validate_database_environment.sh runtime
