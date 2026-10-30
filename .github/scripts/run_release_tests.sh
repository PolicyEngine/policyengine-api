#!/usr/bin/env bash

# Run one shard of the release test suite (make test) in push.yml's
# release-tests job, which the staging deploy needs.
#
# make test collects the whole suite, and the pytest plugin
# tests/release_test_shard_plugin.py keeps only this shard's tests and writes
# what it collected and kept to RELEASE_TEST_SHARD_REPORT_DIRECTORY
# (scripts/release_test_shards.py explains the split).
#
# Deployment settings (route implementations, database policies, Cloud Run and
# v2 database targets, and signed-in user authentication) must not leak into
# the tests. The release-tests job sets none of them, and this script removes
# them anyway, as it did when the tests ran inside the staging deploy job. The
# local Redis runtime-cache settings come from the step's env.
#
# Environment:
#   RELEASE_TEST_SHARD_INDEX             this shard, from 1
#   RELEASE_TEST_SHARD_COUNT             how many shards the suite runs in
#   RELEASE_TEST_SHARD_REPORT_DIRECTORY  where the plugin writes its report

set -euo pipefail

: "${RELEASE_TEST_SHARD_INDEX:?RELEASE_TEST_SHARD_INDEX is required}"
: "${RELEASE_TEST_SHARD_COUNT:?RELEASE_TEST_SHARD_COUNT is required}"
: "${RELEASE_TEST_SHARD_REPORT_DIRECTORY:?RELEASE_TEST_SHARD_REPORT_DIRECTORY is required}"

exec env \
  -u DEPLOYMENT_ENVIRONMENT \
  -u ROUTE_IMPL_HEALTH \
  -u ROUTE_IMPL_SPECIFICATION \
  -u ROUTE_IMPL_METADATA \
  -u ROUTE_IMPL_POLICY \
  -u ROUTE_IMPL_HOUSEHOLD \
  -u DB_READ_POLICY \
  -u DB_WRITE_POLICY \
  -u DB_READ_HOUSEHOLD \
  -u DB_WRITE_HOUSEHOLD \
  -u CLOUD_RUN_SERVICE \
  -u CLOUD_RUN_RUNTIME_CACHE_ENVIRONMENT \
  -u CLOUD_RUN_RUNTIME_CACHE_URL_SECRET \
  -u CLOUD_RUN_RUNTIME_CACHE_CA_CERT_SECRET \
  -u CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET \
  -u CLOUD_RUN_MIN_INSTANCES \
  -u CLOUD_RUN_SERVICE_MIN_INSTANCES \
  -u CLOUD_RUN_MAX_INSTANCES \
  -u V2_SUPABASE_PROJECT_REF \
  -u V2_SUPABASE_ENVIRONMENT \
  -u V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE \
  -u PRODUCTION_V2_SUPABASE_PROJECT_REF \
  -u PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE \
  -u PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME \
  -u PUBLIC_API_AUTH_REQUIRED \
  -u PUBLIC_API_AUTH_ISSUER \
  -u PUBLIC_API_AUTH_AUDIENCE \
  PYTEST_ADDOPTS="-p tests.release_test_shard_plugin" \
  make test
