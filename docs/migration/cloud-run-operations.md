# Cloud Run Operations (living reference)

This is the single living reference for how API v1's Cloud Run deployments work. It is
edited in place whenever behavior changes. Per-stage records (bootstrap commands,
acceptance-check evidence, one-off measurements) are append-only documents under
`history/` and
are never updated to match later reality.

Configuration **values** live in two layers, both source of truth for their scope:
`.github/scripts/cloud_run_env.sh` holds the defaults (CPU, memory, runtime shape,
secrets, service names), and **per-job `env:` pins in `.github/workflows/push.yml`
override them per track** (e.g. production `CLOUD_RUN_MAX_INSTANCES`). To change what a
track deploys, edit the job pin, not just the default — job pins win. Values are
intentionally not duplicated here; this document explains the **semantics**.

## Topology

- The public host `api.policyengine.org` is served by the external HTTPS load
  balancer. Its URL map sends requests through `bs-cloud-run` and the regional
  serverless network endpoint group to the production Cloud Run service.
- Two Cloud Run services in `policyengine-api` / `us-central1`:
  - **`policyengine-api`** — the production candidate. Every push to master deploys a
    tagged `--no-traffic` revision (`stage3-prod-*`). CI resolves the tag once, tests
    its exact revision, then assigns the stable service URL to that revision after
    integration tests.
  - **`policyengine-api-staging`** — the staging track's service (split from the
    production service in migration PR 4, Stage 1). Staging jobs pin
    `CLOUD_RUN_SERVICE: policyengine-api-staging`; unit tests enforce that every
    service-targeting Cloud Run job carries an explicit pin and that no staging job can
    touch production traffic.
- The Docker image name is decoupled from the service name (`CLOUD_RUN_IMAGE_NAME`):
  production reuses the image built by the staging track, so both tracks push and pull
  `policyengine-api:<sha>` regardless of service.

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
  `initialDelaySeconds 240 + 24 x 10s = 480s` — the platform maximum.

  Boot-to-ready is now the ~371s p90 import **plus** the startup warmup (below), so
  every boot exceeds 240s. A high `initialDelaySeconds` therefore no longer delays
  any real scale-out — the earlier reason for keeping it low (holding sub-240s boots
  to a full 240s; see the import-only distribution above) no longer applies, because
  no boot is that fast. Sizing to the 480s maximum minimises killed-and-retried
  boots, which are the costly failure (a killed boot loses its whole boot plus a
  retry and fails a CI deploy).

  Be clear-eyed about what this buys: the warmup consumes most of the headroom the
  wider window adds. p90 boot-to-ready rises from ~371s (import only) to ~420s
  (import + warmup), so the slack under the ceiling stays ~60s — roughly what it was
  at 420s before — and the **far tail can still exceed 480s and be killed-and-retried**.
  We are now at the platform ceiling; the only remaining lever is cutting boot time
  itself (prebuilding the tax-benefit system into the image — see below), not a wider
  probe window.

  **Startup warmup — why readiness depends on more than the import.** Building the
  tax-benefit systems at import does not compile the per-simulation machinery
  (parameter-tree materialisation, the formula graph). The **first** calculate on a
  fresh worker paid that cost — measured at ~121s — and `/readiness-check` returned
  200 before it, so the probe (and health checks, and smoke tests) saw a "ready"
  instance whose first real request still took two minutes.
  `policyengine_api.warmup.run_startup_warmup` now runs a throwaway calculate per
  country (default US; override with `POLICYENGINE_API_WARMUP_COUNTRIES`, disable
  with `POLICYENGINE_API_STARTUP_WARMUP=0`) from `asgi.py` before the worker serves,
  and `/readiness-check` returns 503 until it completes
  (`policyengine_api.readiness`). Verified locally: after the warmup a cold
  test-payload calculate drops from ~121s to ~10s. This is the fix for the note that
  used to live here — deferring the build lazily relocated the cost onto the first
  request, where readiness lied; warming it at startup pays the cost off the request
  path and makes readiness honest, at the cost of a longer (but bounded) boot.

  The lasting fix is still cutting boot time: **~82% of the import is constructing
  the US tax-benefit system** (`policyengine_api.country` builds all five countries
  at import; US alone is ~90% of that, and `CountryTaxBenefitSystem()` is ~91% of the
  per-country cost). Baking a prebuilt system into the image would shrink both the
  import and the warmup and let the window come back down.
- **Scaling pins live in `push.yml` per job**: production `max-instances 8`, staging
  `min 0 / max 1`. Production was `max-instances 4` through Stage 10; it was raised to
  8 for the 100% Cloud Run cutover because at the 50/50 split the service already sat
  pinned at the ceiling of 4 during the daytime peak (`instance_count` flatlined at
  4.0), so carrying all traffic needs the extra headroom.
- **Warm capacity is applied by CI on every deploy as a service-level `--min`**, via
  the `CLOUD_RUN_SERVICE_MIN_INSTANCES` env (production 2, staging 0). CI keeps the
  revision-level `--min-instances 0`, because a revision-level minimum keeps a warm
  16Gi instance alive per accumulated `stage3-*` tag.

  **The flag names differ by one word and mean opposite things:** service-level
  warm capacity is `--min` (or the `run.googleapis.com/minScale` annotation on the
  *service* metadata); `--min-instances` is the *revision-level* setting and is the
  per-tag cost bomb. `--min` requires a recent gcloud (it does not exist in 461); the
  CI runners and the deploy scripts assume a current gcloud. The deploy passes both
  flags on every deploy — `--min-instances 0 --min ${CLOUD_RUN_SERVICE_MIN_INSTANCES}`
  — so the floor is asserted in code, not carried only as live service state.

  To change the floor, edit `CLOUD_RUN_SERVICE_MIN_INSTANCES` in `push.yml` (and the
  default in `cloud_run_env.sh`); the next production deploy applies it. To apply it
  out-of-band between deploys:

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

  This setting was first applied before the Cloud Run traffic migration and is
  now asserted by every deployment. Verify it after configuration changes:

  ```bash
  gcloud run services describe policyengine-api \
    --project policyengine-api --region us-central1 --format yaml | grep -i minscale
  # expect a service-level minScale annotation; a minScale under
  # spec.template (revision-level) would be the per-tag cost bomb — remove it.
  ```

  **Current value: 2.** Originally set to 1 on 2026-07-08 (via the YAML-replace
  fallback, since the gcloud in use lacked `--min`), raised to 2 on 2026-07-22 by
  the same route, and codified into the deploy config on 2026-07-23 (env
  `CLOUD_RUN_SERVICE_MIN_INSTANCES`) so it is no longer live-state-only. One warm
  instance meant every
  burst beyond a single instance's capacity landed on a cold boot; two warm
  instances carry the burst during the ~161s a scaled-out instance takes to become
  ready. Cost is ~$131/month per warm instance at 4 vCPU / 16Gi (idle CPU
  $0.0000025/vCPU-s, idle memory $0.0000025/GiB-s — memory gets no idle discount and
  is ~80% of it), so trimming the memory allocation is the lever if this needs to
  get cheaper.

  Rationale: the user-facing scale-from-zero wake was measured at 282.8s — 17s under
  the 300s request timeout — so a cold start must never sit on a public request path.

Consequences to keep in mind:

- An instance is "started" when its port is bound, before the application can
  answer. The HTTP startup probe prevents Cloud Run from routing requests to
  that instance until `/readiness-check` succeeds.
- **Cold-start and readiness measurements must be taken from `/readiness-check` turning
  healthy**, not from instance start or port bind — the bind time is no longer meaningful.
- Readiness in CI is governed by `.github/scripts/health_check.sh` polling
  `/readiness-check` (defaults: 900s budget, 5s interval, 15s per-request `--max-time`;
  all env-overridable).

## Automated revision promotion and rollback

The push workflow serializes deployments and never promotes `LATEST` or a
mutable tag. For both staging and production it:

1. captures the stable URL and sole 100%-serving revision;
2. deploys a tagged revision with `--no-traffic`;
3. resolves the tag to an exact ready revision and immutable image digest;
4. tests the tagged URL;
5. re-resolves the tag and requires its exact revision and image digest to
   remain unchanged;
6. verifies that stable traffic still matches the captured revision;
7. assigns 100% to the exact tested revision with `--to-revisions`; and
8. health-checks the stable URL.

Promotion and stable verification are allowed to report failure long enough for
the workflow to run its rollback step. That step uses the same guarded command
with the revisions swapped, restores the captured revision, verifies both
control-plane traffic and stable health, and then leaves the deployment red.
This rollback only covers immediate deployment failures; later operational
rollback remains an explicit incident-response action.

## Simulation entrypoint deployment configuration

`SIM_ENTRYPOINT` is a GitHub Actions Environment variable configured separately
in the existing `staging` and `production` environments. Environment-bound
jobs expose it as the same-named environment variable. Deployment validation,
Cloud Run configuration, and the model-version compatibility check all require
only the URL selected by that value:

- `old_gateway_direct` requires `OLD_SIMULATION_GATEWAY_URL`;
- `cloud_run_simulation_entrypoint` requires
  `SIMULATION_ENTRYPOINT_URL`.

`OLD_SIMULATION_GATEWAY_URL` is a non-secret repository-level GitHub Actions
variable. `SIMULATION_ENTRYPOINT_URL` is a GitHub Actions Environment secret
configured separately in those same environments. Each environment-bound job
exposes both values under their same-named environment variables and passes
them to the deployed service as runtime configuration. If both URLs are
configured, both are retained on a revision, but an unselected future URL does
not block a direct-Modal deployment. The legacy `SIMULATION_API_URL` secret is
intentionally unsupported: its value is opaque, cannot be audited, and must
not silently choose a deployment upstream.

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

# Readiness
curl -s -o /dev/null -w '%{http_code}\n' "$SERVICE_URL/readiness-check"
```

## Public load-balancer routing

`lb-api` must use `bs-cloud-run` as its single default backend. It must not
contain a weighted default action or reference a retired backend. Inspect the
complete URL map before and after any intended routing change because
`url-maps import` replaces the entire resource:

```bash
gcloud compute url-maps describe lb-api --project policyengine-api \
  --format='yaml(defaultService,defaultRouteAction,pathMatchers)'
curl -s -o /dev/null -w '%{http_code}\n' \
  https://api.policyengine.org/readiness-check
```

Application rollback restores the previously serving Cloud Run revision. It
does not change DNS or the load-balancer backend.

## History index

- `history/migration-pr1-baseline-runbook.md` — PR 1 baseline capture
- `history/migration-pr2-fastapi-shell-runbook.md` — PR 2 FastAPI/ASGI shell
- `history/migration-pr3-cloud-run-candidate-runbook.md` — PR 3 candidate/promote
  pipeline (documents the pre-Stage-1 single-service behavior)
- `history/pr4-stage1-staging-service-runbook.md` — PR 4 Stage 1 staging service split,
  startup stabilization, and acceptance checks
