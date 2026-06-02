# PR 3 Cloud Run Candidate Runbook

PR 3 adds a production-configured Cloud Run candidate for the FastAPI ASGI
shell. It does not move user traffic.

## Included

- Cloud Run Docker runtime for `policyengine_api.asgi:app`.
- Tagged no-traffic Cloud Run revisions deployed on both the staging and
  production tracks.
- Runtime environment configuration for the production Cloud SQL instance and
  the existing simulation gateway.
- The same live staging integration suite against both the App Engine staging
  URL and the tagged Cloud Run staging URL.
- Production smoke tests against the tagged Cloud Run URL, including an
  internal simulation-gateway health probe.

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
- Staging revision tag: `stage3-staging-${GITHUB_RUN_NUMBER}-${GITHUB_SHA::7}`
- Production revision tag: `stage3-prod-${GITHUB_RUN_NUMBER}-${GITHUB_SHA::7}`

## Post-Merge Flow

The `Push` workflow now uses two deployment tracks.

Staging:

1. Deploy an App Engine staging version.
2. Build and deploy a tagged Cloud Run staging revision with no traffic.
3. Run the same live integration suite against both URLs in parallel:

```bash
python -m pytest \
  tests/integration/test_live_calculate.py \
  tests/integration/test_live_economy.py \
  tests/integration/test_live_budget_window_cache.py \
  -v
```

Production:

1. After both staging integration jobs pass, run the production model-version
   alignment check.
2. Deploy/promote the App Engine production version.
3. Deploy a tagged Cloud Run production revision with no traffic.

The Cloud Run deploy command still uses:

```bash
gcloud run deploy policyengine-api \
  --tag "$CLOUD_RUN_TAG" \
  --no-traffic
```

The production Cloud Run job resolves the tagged URL and runs:

```bash
python -m pytest tests/integration/test_cloud_run_candidate.py -v
```

Failure marks the deployment workflow red, but App Engine remains the production
traffic target because Cloud Run is not assigned traffic and the public URL is
not migrated. Smoke tests against the production candidate must be read-only.

## Manual Smoke

After GitHub Actions prints the candidate URL:

```bash
curl -i "$CLOUD_RUN_CANDIDATE_URL/health"
curl -i "$CLOUD_RUN_CANDIDATE_URL/readiness-check"
curl -i "$CLOUD_RUN_CANDIDATE_URL/liveness-check"
curl -i "$CLOUD_RUN_CANDIDATE_URL/health/simulation-gateway"
curl -i "$CLOUD_RUN_CANDIDATE_URL/us/metadata"
```

Expected behavior:

- `/health` returns FastAPI JSON: `{"status":"healthy"}`.
- `/health/simulation-gateway` returns FastAPI JSON confirming the existing
  simulation gateway client can initialize and reach the gateway health check.
- `/readiness-check` and `/liveness-check` return existing Flask text `OK`.
- `/us/metadata` returns the existing v1 metadata contract from Cloud SQL.

## Rollback

No user traffic is routed to the Cloud Run candidate in this PR. If the staging
Cloud Run track fails, production deployment is blocked. If the production Cloud
Run candidate fails, leave App Engine as production-primary and fix the Cloud Run
deploy path in a follow-up commit.
