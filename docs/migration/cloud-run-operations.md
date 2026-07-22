# Cloud Run Operations (living reference)

This is the single living reference for how API v1's Cloud Run deployments work. It is
edited in place whenever behavior changes. Per-stage records (bootstrap commands,
exit-gate evidence, one-off measurements) are append-only documents under `history/` and
are never updated to match later reality.

Configuration **values** live in two layers, both source of truth for their scope:
`.github/scripts/cloud_run_env.sh` holds the defaults (CPU, memory, runtime shape,
secrets, service names), and **per-job `env:` pins in `.github/workflows/push.yml`
override them per track** (e.g. production `CLOUD_RUN_MAX_INSTANCES`). To change what a
track deploys, edit the job pin, not just the default — job pins win. Values are
intentionally not duplicated here; this document explains the **semantics**.

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

The app import is slow (measured container boot p50 171.5s / p95 215.2s over 7 days,
~161–168s on cpu-boosted revisions; dominated by `policyengine_api/country.py`
instantiating five country packages — see
[`history/pr4-stage2-runtime-timing.md`](history/pr4-stage2-runtime-timing.md)) and
Cloud Run hard-caps total startup-probe time at 240s — the default TCP probe already
sits at that cap, and **no probe configuration can extend it**. Two mitigations are
therefore built in:

- `gcp/cloud_run/start.sh` runs **gunicorn with `uvicorn.workers.UvicornWorker` and no
  `--preload`**: the gunicorn master binds the listen socket in milliseconds (satisfying
  the startup probe immediately), and the import happens in the worker after fork.
  `--timeout 0` is required — a worker mid-import does not heartbeat, and gunicorn's
  default 30s watchdog would kill it. `--keep-alive 5` and `--forwarded-allow-ips '*'`
  preserve the previous uvicorn keep-alive and proxy-header behavior. Worker recycling
  (`--max-requests`) is deliberately NOT enabled: with 2 workers and a multi-minute
  re-import that runs without cpu-boost (and CPU-throttled at idle), recycling risks
  correlated zero-ready-worker windows; it needs its own qualification before adoption.
- Candidate deploys set `--cpu-boost` to shorten the import (instance startup only).

## Runtime shape and scaling (from the Stage 2 qualification)

Values measured and justified in
[`history/pr4-stage2-runtime-timing.md`](history/pr4-stage2-runtime-timing.md):

- **`WEB_CONCURRENCY=2`** — the engine is GIL-bound; two worker processes materially
  outperform one on the 4-vCPU instance. Set via the deploy script's env vars.
- **`--concurrency 6`** — admission control is what keeps the two-worker instance
  memory-safe in 16Gi; excess load queues at the platform and fails as client timeouts
  rather than dying in-instance. Raised from the original 4 on 2026-07-21 (re-qualified
  by a dedicated 30-min soak — memory peaked 61%, zero OOM/5xx; see the 2026-07-21
  amendment in `history/pr4-stage2-runtime-timing.md`) to stop bot-burst scale-out
  churn: the autoscaler targets ~60% of concurrency, so c4 spawned instances at ~2.4
  sustained concurrent requests. **Both knobs are pinned explicitly on every deploy**:
  gcloud inherits unspecified template fields (a mid-campaign CI deploy once shipped an
  inherited test concurrency), and `--concurrency default` resolves to the *platform*
  default (640), not the historical 80.
- **`--startup-probe httpGet.path=/readiness-check` — pinned on every deploy.**
  Cloud Run's default is a *TCP* probe, which passes the instant gunicorn's master
  binds the port, long before a worker finishes importing (the import runs
  post-fork; `--preload` is deliberately unset). Cloud Run therefore treated a
  booting instance as "started" and routed live traffic onto it, where requests
  queued until the 300s timeout — the "no available instance" 500s and 504s seen on
  scale-out bursts. Probing `/readiness-check` over HTTP makes Cloud Run withhold
  traffic until the app can actually serve.

  **Sizing it is constrained by measured boot times.** Boot-to-ready across 48
  boots over 7 days (2026-07-14→21), measured from each instance's
  `Starting gunicorn` to its last `Application startup complete`:

  | p50 | p90 | p95 | max |
  |---|---|---|---|
  | 201s | 371s | 417s | 503s |

  The tail is worst under CPU contention — i.e. during the very bursts that trigger
  scale-out. (Stage 2's "~161s import" measures only the import step on an
  uncontended instance; it is **not** boot-to-ready and must not be used to size
  this.)

  Cloud Run caps `failureThreshold x periodSeconds` at 240s **and**
  `initialDelaySeconds` at 240s, and shuts the container down past their sum. We run
  `initialDelaySeconds 180 + 24 x 10s = 420s`. The threshold/period half is already
  at its ceiling, so `initialDelaySeconds` is the only way to widen the window; it
  is additive (no probe runs during it) but also delays availability for instances
  that boot faster than it. Trade-off against the distribution above:

  | initialDelay | window | boots killed | boots delayed | median penalty |
  |---|---|---|---|---|
  | 120 | 360s | 12.5% | 8.3% | 31s |
  | **180 (current)** | **420s** | **6.2%** | **22.9%** | **25s** |
  | 240 (max) | 480s | 2.1% | 77.1% | 50s |

  A delayed instance loses tens of seconds; a **killed** one loses its whole boot
  plus a retry (400s+) and fails the deploy if it happens in CI — so the asymmetry
  favours a wider window. 240 was rejected because it holds 77% of instances to a
  full 240s, slowing every scale-out.

  **Residual risk: ~6% of boots still exceed 420s and will be killed and retried**,
  which can fail a deploy. That is accepted deliberately — the alternative (TCP)
  served real users 5xx from instances that were never ready. Qualified 2026-07-22
  on a `--no-traffic` revision: Cloud Run stored the config exactly as specified and
  the revision reached `Ready` on a 181.6s boot.

  The real fix is cutting boot time — **~82% of it is constructing the US
  tax-benefit system** (`policyengine_api.country` builds all five countries at
  import; US alone is ~90% of that, and `CountryTaxBenefitSystem()` is ~91% of the
  per-country cost). At a 20s boot this would be `initialDelay 0` with a 240s window
  covering every boot. Note that lazily deferring the build does **not** help: it
  relocates the cost onto the first request, where readiness would lie and a user
  would absorb it.
- **Scaling pins live in `push.yml` per job**: production `max-instances 4` (peak real
  traffic ~11 RPS, mostly cached/light; ~1–2 concurrent uncached calculates per
  instance), staging `min 0 / max 1`.
- **Warm capacity is a service-level setting made manually, once** — CI keeps
  revision-level `--min-instances 0`, because revision-level minimums keep a warm 16Gi
  instance alive per accumulated `stage3-*` tag.

  **The flag names differ by one word and mean opposite things:** service-level
  warm capacity is `--min` (or the `run.googleapis.com/minScale` annotation on the
  *service* metadata); `--min-instances` is the *revision-level* setting and is the
  per-tag cost bomb. `--min` requires a recent gcloud (it does not exist in 461).

  ```bash
  gcloud run services update policyengine-api \
    --project policyengine-api --region us-central1 \
    --min 2
  ```

  On older gcloud, set it by exporting the service YAML and adding
  `run.googleapis.com/minScale: "2"` to the **service** `metadata.annotations`
  (never under `spec.template`), then `gcloud run services replace` — which
  requires the Cloud Resource Manager API enabled on the project:

  ```bash
  gcloud run services describe policyengine-api --project policyengine-api \
    --region us-central1 --format export > svc.yaml
  # edit ONLY metadata.annotations."run.googleapis.com/minScale", then diff to
  # confirm a single changed line before applying
  gcloud run services replace svc.yaml --project policyengine-api --region us-central1
  ```

  `replace` re-applies the whole spec and prints "Creating Revision", but Cloud Run
  deduplicates an unchanged template — the serving revision and its tag are
  preserved. Verify that: `status.latestReadyRevisionName` and the 100%-traffic
  entry should be unchanged afterwards.

  **When:** once, immediately after the Stage 3 PR merges — before evaluating the
  Stage 3 exit gates (the idle-readiness gate cannot pass without it) and before any
  public traffic. **Verify** it took, and re-verify during ramp incident response:

  ```bash
  gcloud run services describe policyengine-api \
    --project policyengine-api --region us-central1 --format yaml | grep -i minscale
  # expect a service-level minScale annotation; a minScale under
  # spec.template (revision-level) would be the per-tag cost bomb — remove it.
  ```

  **Current value: 2.** Originally set to 1 on 2026-07-08 (via the YAML-replace
  fallback, since the gcloud in use lacked `--min`), raised to 2 on 2026-07-22 by
  the same route. One warm instance meant every
  burst beyond a single instance's capacity landed on a cold boot; two warm
  instances carry the burst during the ~161s a scaled-out instance takes to become
  ready. Cost is ~$131/month per warm instance at 4 vCPU / 16Gi (idle CPU
  $0.0000025/vCPU-s, idle memory $0.0000025/GiB-s — memory gets no idle discount and
  is ~80% of it), so trimming the memory allocation is the lever if this needs to
  get cheaper.

  Rationale: the user-facing scale-from-zero wake was measured at 282.8s — 17s under
  the 300s request timeout — so a cold start must never sit on a public request path.

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

## URL map weight changes (the ramp lever, Stages 5 and 9–11)

Once the load balancer exists (Stage 4), every traffic shift between App Engine and
Cloud Run is a weight edit on the `lb-api` URL map — and **only** via this procedure.
Console edits leave no audit trail, and `url-maps import` **replaces the entire map**,
so an un-diffed import can silently drop routing config:

```bash
gcloud compute url-maps export lb-api --project policyengine-api \
  --destination docs/migration/urlmap/$(date -u +%Y%m%dT%H%M%SZ)-lb-api.yaml
# 1. diff against the last committed snapshot — investigate ANY unexpected delta
# 2. edit ONLY the two weight values (must sum to 100)
# 3. import, then re-export and verify the readback matches the edit
gcloud compute url-maps import lb-api --project policyengine-api --source <edited>.yaml --quiet
# 4. verify in-band before trusting it: ~20 header-sampled curls against the LB
#    counting X-PolicyEngine-Backend values
# 5. commit the new snapshot to docs/migration/urlmap/
```

Rollback during a ramp = the same procedure with `app_engine=100, cloud_run=0`
(measured propagation is minutes; rehearsed in Stage 9).

## History index

- `history/migration-pr1-baseline-runbook.md` — PR 1 baseline capture
- `history/migration-pr2-fastapi-shell-runbook.md` — PR 2 FastAPI/ASGI shell
- `history/migration-pr3-cloud-run-candidate-runbook.md` — PR 3 candidate/promote
  pipeline (documents the pre-Stage-1 single-service behavior)
- `history/pr4-stage1-staging-service-runbook.md` — PR 4 Stage 1 staging service split,
  startup de-flake, and exit gates
