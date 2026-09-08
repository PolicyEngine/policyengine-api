#!/usr/bin/env bash

set -euo pipefail

required=(
  DEPLOYMENT_ENVIRONMENT
  ROUTE_IMPL_HOUSEHOLD
  DB_READ_HOUSEHOLD
  DB_WRITE_HOUSEHOLD
  V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE
  V2_FAILURE_DATABASE_URL_SECRET_RESOURCE
  POLICYENGINE_DB_READONLY_PASSWORD_SECRET
  HOUSEHOLD_MIRROR_OPERATOR_IDENTITY
  ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY
)

for setting in "${required[@]}"; do
  if [[ -z "${!setting:-}" ]]; then
    printf '%s is required for the Stage 11 staging exercise\n' "${setting}" >&2
    exit 1
  fi
done

if [[ "${DEPLOYMENT_ENVIRONMENT}" != "staging" ]]; then
  echo "The Stage 11 live exercise may run only against staging." >&2
  exit 1
fi
if [[ "${ROUTE_IMPL_HOUSEHOLD}" != "flask_fallback" ]]; then
  echo "ROUTE_IMPL_HOUSEHOLD must remain flask_fallback during Stage 11." >&2
  exit 1
fi
if [[ "${DB_READ_HOUSEHOLD}" != "cloud_sql" ]]; then
  echo "DB_READ_HOUSEHOLD must remain cloud_sql during Stage 11." >&2
  exit 1
fi
if [[ "${DB_WRITE_HOUSEHOLD}" != "cloud_sql" ]]; then
  echo "The staging candidate must begin with DB_WRITE_HOUSEHOLD=cloud_sql." >&2
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
if [[ "${HOUSEHOLD_MIRROR_OPERATOR_IDENTITY}" != \
  "${ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY}" ]]; then
  echo "The Stage 11 event-processing identity is not authorized." >&2
  exit 1
fi

bash .github/scripts/validate_database_environment.sh runtime
