# PR 3 Cloud Run Candidate Runbook

PR 3 adds a Cloud Run candidate for the FastAPI ASGI shell. It uses staging
data-plane configuration and does not move user traffic.

## Included

- Cloud Run Docker runtime for `policyengine_api.asgi:app`.
- Tagged no-traffic Cloud Run revisions deployed after staging integration
  tests pass.
- Runtime environment configuration for a non-production Cloud SQL instance and
  the existing simulation gateway.
- Smoke tests against the tagged Cloud Run URL.

## Not Included

- No public API host traffic shift.
- No Cloud Run traffic ramp.
- No native FastAPI route migration beyond `/health`.
- No Supabase, Alembic, SQLAlchemy model, or Modal compute migration.
- No App Engine retirement.

## Resource Defaults

- Project: `policyengine-api`
- Region: `us-central1`
- Service: `policyengine-api`
- Artifact Registry repository: `policyengine-api`
- Cloud SQL instance: supplied by staging `CLOUD_RUN_CLOUD_SQL_INSTANCE`; this
  must not be `policyengine-api:us-central1:policyengine-api-data`.
- Revision tag: `stage3-${GITHUB_RUN_NUMBER}-${GITHUB_SHA::7}`

## Post-Merge Flow

The `Push` workflow deploys and tests App Engine staging first. Only after
staging integration tests pass, it builds and deploys a Cloud Run revision with:

```bash
gcloud run deploy policyengine-api \
  --tag "$CLOUD_RUN_TAG" \
  --no-traffic
```

The workflow then resolves the tagged URL and runs:

```bash
python -m pytest tests/integration/test_cloud_run_candidate.py -v
```

Failure marks the deployment workflow red, but App Engine remains the production
traffic target. The Cloud Run candidate must use staging DB credentials and a
non-production Cloud SQL instance.

## Manual Smoke

After GitHub Actions prints the candidate URL:

```bash
curl -i "$CLOUD_RUN_CANDIDATE_URL/health"
curl -i "$CLOUD_RUN_CANDIDATE_URL/readiness-check"
curl -i "$CLOUD_RUN_CANDIDATE_URL/liveness-check"
curl -i "$CLOUD_RUN_CANDIDATE_URL/us/metadata"
```

Expected behavior:

- `/health` returns FastAPI JSON: `{"status":"healthy"}`.
- `/readiness-check` and `/liveness-check` return existing Flask text `OK`.
- `/us/metadata` returns the existing v1 metadata contract from the
  non-production Cloud SQL instance.

## Rollback

No user traffic is routed to the Cloud Run candidate in this PR. If the candidate
fails, leave App Engine as production-primary and fix the Cloud Run deploy path
in a follow-up commit.
