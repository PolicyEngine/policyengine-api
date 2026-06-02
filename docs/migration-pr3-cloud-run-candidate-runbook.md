# PR 3 Cloud Run Candidate Runbook

PR 3 adds a production-configured Cloud Run candidate for the FastAPI ASGI
shell. It makes the Cloud Run service URL live after staged validation, but it
does not migrate the public App Engine/custom API URL.

## Included

- Cloud Run Docker runtime for `policyengine_api.asgi:app`.
- Tagged no-traffic Cloud Run revisions deployed on both the staging and
  production tracks, then promoted to the Cloud Run service URL after tests.
- Runtime environment configuration for the production Cloud SQL instance and
  the existing simulation gateway.
- The same live staging integration suite against both the App Engine staging
  URL and the tagged Cloud Run staging URL.
- Production smoke tests against the tagged Cloud Run URL, including an
  internal simulation-gateway health probe.

## Not Included

- No public App Engine/custom API host traffic shift.
- No percent-based Cloud Run traffic ramp; the tested tag is promoted to 100%
  of the Cloud Run service URL.
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
4. Promote the tested Cloud Run staging tag to 100% of the Cloud Run service
   URL and health-check that service URL.

Production:

1. After both staging integration jobs pass, run the production model-version
   alignment check.
2. Deploy/promote the App Engine production version.
3. Deploy a tagged Cloud Run production revision with no traffic.
4. Smoke-test the tagged Cloud Run production URL.
5. Promote the tested production tag to 100% of the Cloud Run service URL and
   health-check that service URL.

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

Then it assigns Cloud Run service traffic to the tested tag:

```bash
gcloud run services update-traffic policyengine-api \
  --to-tags "$CLOUD_RUN_TAG=100"
```

Failure marks the deployment workflow red. App Engine remains the public
production traffic target because the public URL is not migrated to Cloud Run.
Smoke tests against the production candidate must be read-only.

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

The public App Engine/custom API URL is not routed to the Cloud Run candidate in
this PR. If the staging Cloud Run track fails, production deployment is blocked.
If the production Cloud Run candidate fails before promotion, leave App Engine
as production-primary and fix the Cloud Run deploy path in a follow-up commit.
If the production Cloud Run service URL is promoted and later regresses, deploy
a fixed tagged revision and promote that tag, or manually shift the Cloud Run
service URL back to a prior healthy revision.
