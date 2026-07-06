# PR 3 Cloud Run Candidate Runbook

> Historical record — describes the pipeline as it was when this PR landed.
> Current behavior: see [`../cloud-run-operations.md`](../cloud-run-operations.md).

PR 3 adds a production-configured Cloud Run candidate for the FastAPI ASGI
shell. It makes the Cloud Run service URL live after staged validation, but it
does not migrate the public App Engine/custom API URL.

## Included

- Cloud Run Docker runtime for `policyengine_api.asgi:app`.
- Tagged no-traffic Cloud Run revisions deployed on both the staging and
  production tracks, then promoted to the Cloud Run service URL after tests.
- Runtime environment configuration for the production Cloud SQL instance and
  the existing simulation gateway.
- Secret Manager-backed Cloud Run runtime credentials, synced manually from
  existing GitHub Actions secrets.
- A dedicated Cloud Run runtime service account, separate from the GitHub deploy
  service account used to run `gcloud`.
- The same live staging integration suite against both the App Engine staging
  URL and the tagged Cloud Run staging URL.
- Production smoke tests against the tagged Cloud Run URL, including the public
  simulation-gateway health probe.
- Tier 1 Cloud Run startup supervision: the container still runs local Redis,
  but the bash startup script tracks Redis and Uvicorn child PIDs explicitly and
  exits if either process dies.

## Not Included

- No public App Engine/custom API host traffic shift.
- No percent-based Cloud Run traffic ramp; the tested tag is promoted to 100%
  of the Cloud Run service URL.
- No native FastAPI route migration beyond `/health`.
- No Supabase, Alembic, SQLAlchemy model, or Modal compute migration.
- No managed Redis, Redis Memorystore, or API v2-alpha-style cache replacement.
- No App Engine secret-handling migration; App Engine deploys still use the
  existing transitional bundle path.
- No App Engine retirement.

## Resource Defaults

- Project: `policyengine-api`
- Region: `us-central1`
- Service: `policyengine-api`
- Artifact Registry repository: `policyengine-api`
- Cloud Run runtime service account:
  `policyengine-api-cr-runtime@policyengine-api.iam.gserviceaccount.com`
- Cloud SQL instance: `policyengine-api:us-central1:policyengine-api-data`
- Staging revision tag: `stage3-staging-${GITHUB_RUN_NUMBER}-${GITHUB_SHA::7}`
- Production revision tag: `stage3-prod-${GITHUB_RUN_NUMBER}-${GITHUB_SHA::7}`
- Secret Manager secrets:
  - `policyengine-api-prod-db-password`
  - `policyengine-api-prod-github-microdata-token`
  - `policyengine-api-prod-anthropic-api-key`
  - `policyengine-api-prod-openai-api-key`
  - `policyengine-api-prod-hugging-face-token`

## Required Runtime IAM

GitHub Actions still authenticates as `${{ secrets.GCP_DEPLOY_SERVICE_ACCOUNT }}`
to deploy App Engine and Cloud Run. Cloud Run itself runs as
`${{ secrets.GCP_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT }}`.

The runtime service account must be:

- granted Cloud SQL client access for
  `policyengine-api:us-central1:policyengine-api-data`;
- allowed to read the five Cloud Run runtime secrets listed above;
- allowed to read the Secret Manager secret referenced by
  `GATEWAY_AUTH_CLIENT_SECRET_RESOURCE`;
- allowed as a service account user for the GitHub deploy service account, so the
  workflow can deploy revisions using that runtime identity.

The manual `Sync Cloud Run secrets` workflow authenticates through Workload
Identity Federation as `${{ secrets.GCP_DEPLOY_SERVICE_ACCOUNT }}`. That deploy
service account must be able to create the five secrets if missing, add secret
versions, and grant the Cloud Run runtime service account Secret Manager access
on those secrets.

## Secret Sync

Run `.github/workflows/sync-cloud-run-secrets.yml` manually from `master` before
the first Cloud Run deployment that uses Secret Manager references, and again
whenever one of the source GitHub secrets is rotated.

The workflow copies these existing GitHub secrets into Secret Manager:

- `POLICYENGINE_DB_PASSWORD`
- `POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `HUGGING_FACE_TOKEN`

The workflow writes secret payloads to `gcloud secrets versions add` through
stdin and does not print secret values. GitHub Actions remains the temporary
source of truth in PR 3. The long-term target is to create, rotate, and manage
these credentials directly in Secret Manager, with GitHub Actions only deploying
Secret Manager references.

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

1. After the App Engine staging version is healthy, deploy the App Engine
   production candidate with `APP_ENGINE_PROMOTE=0` and health-check its version
   URL. This version must not receive production traffic yet.
2. In parallel, run the staging integration jobs and promote the tested Cloud
   Run staging tag to the Cloud Run service URL.
3. After the staging gates pass, run the production model-version alignment
   check.
4. Promote the already-deployed App Engine production candidate to receive
   public production traffic.
5. Deploy a tagged Cloud Run production revision with no traffic.
6. Smoke-test the tagged Cloud Run production URL.
7. Promote the tested production tag to 100% of the Cloud Run service URL and
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
curl -i "$CLOUD_RUN_CANDIDATE_URL/simulation-gateway-check"
curl -i "$CLOUD_RUN_CANDIDATE_URL/us/metadata"
```

Expected behavior:

- `/health` returns FastAPI JSON: `{"status":"healthy"}`.
- `/simulation-gateway-check` returns FastAPI JSON confirming the existing
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
