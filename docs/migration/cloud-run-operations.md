# Cloud Run Operations (living reference)

This is the single living reference for how API v1's Cloud Run deployments work. It is
edited in place whenever behavior changes. Per-stage records (bootstrap commands,
exit-gate evidence, one-off measurements) are append-only documents under `history/` and
are never updated to match later reality.

Configuration **values** (CPU, memory, scaling, secrets, service names) live in
`.github/scripts/cloud_run_env.sh` and the deploy scripts — they are the source of truth
and are intentionally not duplicated here. This document explains the **semantics**.

## Topology

- The public host `api.policyengine.org` is served by **App Engine** (bound via
  `gcp/dispatch.yaml`). No public traffic reaches Cloud Run until the load-balancer
  stages of the host cutover plan (`api-v1-pr4-cloud-run-host-cutover-execution-plan.md`
  in the planning folder).
- Two Cloud Run services in `policyengine-api` / `us-central1`:
  - **`policyengine-api`** — the production candidate. Every push to master deploys a
    tagged `--no-traffic` revision (`stage3-prod-*`), which is promoted to the service
    URL after integration tests. Only CI and its own health checks call this URL today.
  - **`policyengine-api-staging`** — the staging track's service (split from the
    production service in migration PR 4, Stage 1). Staging jobs pin
    `CLOUD_RUN_SERVICE: policyengine-api-staging`; unit tests enforce that every
    service-targeting Cloud Run job carries an explicit pin and that no staging job can
    touch production traffic.
- The Docker image name is decoupled from the service name (`CLOUD_RUN_IMAGE_NAME`):
  production reuses the image built by the staging track, so both tracks push and pull
  `policyengine-api:<sha>` regardless of service.
- Every API response carries `X-PolicyEngine-Backend` (`app_engine` or `cloud_run`) for
  in-band backend verification during the host-cutover traffic ramps.

## Startup behavior

The app import is slow (~230s cold: `policyengine_api/country.py` instantiates five
country packages, ~210s of it) and Cloud Run hard-caps total startup-probe time at 240s —
the default TCP probe already sits at that cap, and **no probe configuration can extend
it**. Two mitigations are therefore built in:

- `gcp/cloud_run/start.sh` runs **gunicorn with `uvicorn.workers.UvicornWorker` and no
  `--preload`**: the gunicorn master binds the listen socket in milliseconds (satisfying
  the startup probe immediately), and the import happens in the worker after fork.
  `--timeout 0` is required — a worker mid-import does not heartbeat, and gunicorn's
  default 30s watchdog would kill it. `--keep-alive 5` and `--forwarded-allow-ips '*'`
  preserve the previous uvicorn keep-alive and proxy-header behavior.
- Candidate deploys set `--cpu-boost` to shorten the import.

Consequences to keep in mind:

- An instance is "started" (port bound) before the app can answer. Requests arriving in
  that window queue until the worker is ready or Cloud Run's request timeout fires. This
  is acceptable while the services carry no public traffic; the min-instances decision in
  the cutover plan's Stage 3 keeps cold imports off the request path before traffic ramps.
- **Cold-start and readiness measurements must be taken from `/readiness-check` turning
  healthy**, not from instance start or port bind — the bind time is no longer meaningful.
- Readiness in CI is governed by `.github/scripts/health_check.sh` polling
  `/readiness-check` (defaults: 900s budget, 5s interval, 15s per-request `--max-time`;
  all env-overridable).

## IAM and bootstrap constraints

- The GitHub deploy service account holds `roles/run.developer`: it can deploy to
  existing services but cannot create the `allUsers` → `roles/run.invoker` binding a new
  service needs, and `deploy_cloud_run_candidate.sh` always deploys `--no-traffic`, which
  gcloud rejects on service creation. **New Cloud Run services are therefore bootstrapped
  manually by a project owner** (placeholder image + IAM binding + runtime service
  account); the first CI deploy replaces the revision entirely. See
  `history/pr4-stage1-staging-service-runbook.md` for the pattern.
- Both services currently run as the dedicated runtime service account and share the
  prod-named Secret Manager secrets and the production Cloud SQL instance. Known
  follow-up: per-service secrets became possible once the services split; migrate in a
  later stage.

## Verification commands

```bash
# Service state, runtime SA, traffic tags
gcloud run services describe policyengine-api \
  --project policyengine-api --region us-central1 \
  --format 'value(status.url, spec.template.spec.serviceAccountName, status.traffic)'

# IAM (expect allUsers -> roles/run.invoker)
gcloud run services get-iam-policy policyengine-api-staging \
  --project policyengine-api --region us-central1

# Readiness and backend identification
curl -s -o /dev/null -w '%{http_code}\n' "$SERVICE_URL/readiness-check"
curl -sI "$SERVICE_URL/readiness-check" | grep -i x-policyengine-backend
```

## History index

- `history/migration-pr1-baseline-runbook.md` — PR 1 baseline capture
- `history/migration-pr2-fastapi-shell-runbook.md` — PR 2 FastAPI/ASGI shell
- `history/migration-pr3-cloud-run-candidate-runbook.md` — PR 3 candidate/promote
  pipeline (documents the pre-Stage-1 single-service behavior)
- `history/pr4-stage1-staging-service-runbook.md` — PR 4 Stage 1 staging service split,
  startup de-flake, and exit gates
