# PR 3 Cloud Run Candidate Runbook

PR 3 adds a production-configured Cloud Run candidate for the FastAPI ASGI
shell. It does not move user traffic.

## Included

- Cloud Run Docker runtime for `policyengine_api.asgi:app`.
- Tagged no-traffic Cloud Run revisions deployed after App Engine production
  promotion.
- Runtime environment configuration for existing Cloud SQL and the existing
  simulation gateway.
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
- Cloud SQL instance: `policyengine-api:us-central1:policyengine-api-data`
- Revision tag: `stage3-${GITHUB_RUN_NUMBER}-${GITHUB_SHA::7}`

## Post-Merge Flow

The `Push` workflow still deploys and promotes App Engine production first. Only
after that succeeds, it builds and deploys a Cloud Run revision with:

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
traffic target.

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
- `/us/metadata` returns the existing v1 metadata contract from Cloud SQL.

## Rollback

No user traffic is routed to the Cloud Run candidate in this PR. If the candidate
fails, leave App Engine as production-primary and fix the Cloud Run deploy path
in a follow-up commit.
