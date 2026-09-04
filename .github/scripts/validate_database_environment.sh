#!/usr/bin/env bash

set -euo pipefail

mode="${1:-}"

require_environment_variables() {
  local missing=()
  local name

  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("${name}")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "Missing required database environment configuration: ${missing[*]}" >&2
    return 1
  fi
}

require_environment_variables DEPLOYMENT_ENVIRONMENT

case "${DEPLOYMENT_ENVIRONMENT}" in
  staging|production) ;;
  *)
    printf 'DEPLOYMENT_ENVIRONMENT=%s is invalid; expected staging or production\n' \
      "${DEPLOYMENT_ENVIRONMENT}" >&2
    exit 1
    ;;
esac

validate_cloud_sql() {
  require_environment_variables \
    POLICYENGINE_DB_INSTANCE_CONNECTION_NAME \
    PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME

  if [[ "${DEPLOYMENT_ENVIRONMENT}" == "staging" ]]; then
    if [[ "${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME}" == \
      "${PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME}" ]]; then
      echo "Staging Cloud SQL must use an instance distinct from production." >&2
      return 1
    fi
  elif [[ "${POLICYENGINE_DB_INSTANCE_CONNECTION_NAME}" != \
    "${PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME}" ]]; then
    echo "Production Cloud SQL does not match the configured production instance." >&2
    return 1
  fi

  local credential_setting_count=0
  local setting
  for setting in \
    POLICYENGINE_DB_READONLY_PASSWORD_SECRET \
    POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET \
    PRODUCTION_POLICYENGINE_DB_READONLY_PASSWORD_SECRET \
    PRODUCTION_POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET; do
    if [[ -n "${!setting:-}" ]]; then
      credential_setting_count=$((credential_setting_count + 1))
    fi
  done
  if (( credential_setting_count > 0 && credential_setting_count < 4 )); then
    echo "All Cloud SQL migration credential resources are required together." >&2
    return 1
  fi
  if (( credential_setting_count == 4 )); then
    if [[ "${DEPLOYMENT_ENVIRONMENT}" == "staging" ]]; then
      if [[ "${POLICYENGINE_DB_READONLY_PASSWORD_SECRET}" == \
        "${PRODUCTION_POLICYENGINE_DB_READONLY_PASSWORD_SECRET}" || \
        "${POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET}" == \
        "${PRODUCTION_POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET}" ]]; then
        echo "Staging Cloud SQL migration credentials must be distinct from production." >&2
        return 1
      fi
    elif [[ "${POLICYENGINE_DB_READONLY_PASSWORD_SECRET}" != \
      "${PRODUCTION_POLICYENGINE_DB_READONLY_PASSWORD_SECRET}" || \
      "${POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET}" != \
      "${PRODUCTION_POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET}" ]]; then
      echo "Production Cloud SQL migration credentials do not match production resources." >&2
      return 1
    fi
  fi
}

validate_supabase() {
  require_environment_variables \
    V2_SUPABASE_PROJECT_REF \
    V2_SUPABASE_ENVIRONMENT \
    PRODUCTION_V2_SUPABASE_PROJECT_REF

  if [[ "${DEPLOYMENT_ENVIRONMENT}" == "staging" ]]; then
    if [[ "${V2_SUPABASE_ENVIRONMENT}" != "staging" ]]; then
      echo "Staging V2_SUPABASE_ENVIRONMENT must be exactly staging." >&2
      return 1
    fi
    if [[ "${V2_SUPABASE_PROJECT_REF}" == \
      "${PRODUCTION_V2_SUPABASE_PROJECT_REF}" ]]; then
      echo "Staging Supabase must use a project distinct from production." >&2
      return 1
    fi
  else
    if [[ "${V2_SUPABASE_PROJECT_REF}" != \
      "${PRODUCTION_V2_SUPABASE_PROJECT_REF}" ]]; then
      echo "Production Supabase does not match the configured production project." >&2
      return 1
    fi
    if [[ "${V2_SUPABASE_ENVIRONMENT}" == "staging" ]]; then
      echo "Production V2_SUPABASE_ENVIRONMENT must not be staging." >&2
      return 1
    fi
  fi
}

validate_runtime_secret() {
  require_environment_variables \
    CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET \
    PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET \
    V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE \
    PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE

  if [[ "${DEPLOYMENT_ENVIRONMENT}" == "staging" ]]; then
    if [[ "${CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET}" == \
      "${PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET}" ]]; then
      echo "Staging v1 runtime must use a database secret distinct from production." >&2
      return 1
    fi
    if [[ "${V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE}" == \
      "${PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE}" ]]; then
      echo "Staging v2 runtime must use a database secret distinct from production." >&2
      return 1
    fi
  else
    if [[ "${CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET}" != \
      "${PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET}" ]]; then
      echo "Production v1 runtime does not match the configured production secret." >&2
      return 1
    fi
    if [[ "${V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE}" != \
      "${PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE}" ]]; then
      echo "Production v2 runtime does not match the configured production secret." >&2
      return 1
    fi
  fi
}

case "${mode}" in
  cloud-sql)
    validate_cloud_sql
    ;;
  supabase)
    validate_supabase
    ;;
  runtime)
    validate_cloud_sql
    validate_supabase
    validate_runtime_secret
    ;;
  *)
    echo "Usage: $0 {cloud-sql|supabase|runtime}" >&2
    exit 1
    ;;
esac
