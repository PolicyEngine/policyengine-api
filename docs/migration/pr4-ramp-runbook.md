# PR 4 Ramp Runbook: App Engine → Cloud Run traffic ramp

> Repeated-use operational document — one pass per ramp step. Executed after Stage 8
> (DNS on the LB, weights 100/0). Weight-change mechanics live in
> [`cloud-run-operations.md`](cloud-run-operations.md) ("URL map weight changes");
> rollback in [`pr4-app-engine-rollback-runbook.md`](pr4-app-engine-rollback-runbook.md).
> Gates are **logs-first**: both backend services log at `sampleRate: 1.0` (verified
> 2026-07-09), so `gcloud logging read` sweeps are exact counts, not samples. Cloud
> Monitoring dashboards/alerts were dropped (user decision 2026-07-09; re-open
> condition below); **there is no automatic failover** — serverless NEGs have no LB
> health checks, so a failed gate is acted on by a human running the rollback runbook.

Ramp ladder: `bs-cloud-run` weight **1 → 5 → 25 → 50 → 100**, holding **~4h** per step
(cut from 24h, user decision 2026-07-09: at this service's volume 4h is statistically
sufficient for the gates, rollback is minutes, and short attended holds beat long
unattended ones given the no-alerts decision). Advance only when every gate below is
green for the full hold. **Carve-out: at least one of the 25% / 50% holds must span the
daily traffic peak window** (mined from 7 days of hourly request counts before the 1%
step) — schedule those two steps so one covers it.

## 0. Shell variables

```bash
export PROJECT=policyengine-api
export HOST=api.policyengine.org        # post-Stage-8 this resolves to the LB
export SNAP_DIR=docs/migration/urlmap
export BASELINE=docs/migration/baselines/canonical-gae-via-lb.json   # from Stage 8
export STEP_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)   # re-export at each weight change
```

## 1. Change the weight (per step)

Follow the ops-doc procedure exactly: export → diff against the last committed snapshot
(fingerprint-only noise expected) → edit the two weights → import → readback → commit a
timestamped snapshot to `$SNAP_DIR`.

**Then wait ≥10 minutes before any sampling gate.** URL-map changes propagate to GFEs
over ~5–10 min; `describe` shows new weights immediately, but traffic follows late
(observed in Stages 4–5). Sampling early produces false gate failures.

## 2. Distribution gate (curl only — header is not CORS-exposed)

`X-PolicyEngine-Backend` has no `Access-Control-Expose-Headers`, so browsers can't read
it; sampling is curl/server-side only.

```bash
for i in $(seq 1 "$N"); do
  curl -sI --max-time 10 "https://$HOST/liveness-check" | tr -d '\r' \
    | awk -F': ' 'tolower($1)=="x-policyengine-backend" {print $2}'
done | sort | uniq -c
```

Acceptable `cloud_run` counts (~mean ± 3σ, binomial; every request must carry the header):

| Step | N | `cloud_run` acceptable |
|---|---|---|
| 1% | 500 | 1–12 |
| 5% | 400 | 7–33 |
| 25% | 200 | 32–68 |
| 50% | 200 | 79–121 |
| 100% | 200 | 200 (zero `app_engine`) |

## 3. Error gate — log sweeps over the hold window

Filter on `bs-*` backend names ONLY: this project's `http_load_balancer` logs also
contain `aef-default-*` entries (App Engine's own front end serving direct traffic),
which are not the LB path.

```bash
# 5xx per backend (run for bs-cloud-run AND bs-app-engine as control)
gcloud logging read 'resource.type="http_load_balancer"
  resource.labels.backend_service_name="bs-cloud-run"
  httpRequest.status>=500 timestamp>="'$STEP_START'"' \
  --project "$PROJECT" --limit 50 \
  --format 'value(timestamp, httpRequest.status, httpRequest.requestUrl, httpRequest.latency, jsonPayload.statusDetails)'

# request volume per backend (exact at sampleRate 1.0)
gcloud logging read 'resource.type="http_load_balancer"
  resource.labels.backend_service_name="bs-cloud-run"
  timestamp>="'$STEP_START'"' \
  --project "$PROJECT" --format 'value(insertId)' | wc -l
```

**Gate: zero steady-state 5xx on `bs-cloud-run`.** One documented exception — the
Stage 5 cold-routing artifact: an isolated 504 cluster (a handful of requests, one
instant, latency ≈300s) coinciding with an instance start is queued-on-boot timeout,
not app failure. Confirm the correlation before excusing it:

```bash
gcloud logging read 'resource.type="cloud_run_revision"
  resource.labels.service_name="policyengine-api"
  textPayload:"Starting new instance" timestamp>="'$STEP_START'"' \
  --project "$PROJECT" --format 'value(timestamp)'
```

Excuse at most one such cluster per hold, only if its timestamps match an instance
start. Any 5xx NOT explained by a boot window, or repeated clusters, fails the gate →
rollback class (a) and investigate. Repeated clusters mean real traffic scales out more
than expected — raise warm capacity (service-level `minScale`, see ops doc) before
retrying the step.

Also track scale-out frequency (the count from the query above): it is the leading
indicator for the 504 window. Record it in the step log even when gates pass.

## 4. Latency gate — baseline comparison (per probe, not pooled)

Run at least twice per hold (after settle, and before advancing):

```bash
python scripts/capture_migration_baseline.py --base-url "https://$HOST" \
  --repetitions 10 > /tmp/ramp-step-$(date -u +%Y%m%dT%H%M%SZ).json
python scripts/compare_migration_baseline.py "$BASELINE" /tmp/ramp-step-*.json
```

**Gate: comparison script exits 0** (per probe: error rate ≤ baseline + 0.1pp, p95 ≤
baseline × 1.20). The canonical baseline is captured at Stage 8 (GAE-via-LB, same path,
weights 100/0) and committed to `docs/migration/baselines/`. Never compare against a
direct-GAE (non-LB) baseline — path overhead would contaminate the delta.

## 5. Functional gate — suites and app E2E

```bash
API_BASE_URL="https://$HOST" python -m pytest \
  tests/integration/test_live_calculate.py \
  tests/integration/test_live_economy.py \
  tests/integration/test_live_budget_window_cache.py -v
```

Green required (economy exercises cross-backend job polling at split weights). Known
flake: the budget-window test can fail under backend queue contention — retry it
isolated before treating as a gate failure. Additionally run the policyengine-app-v2
E2E suite against production per its own repo instructions.

## 6. Advance, hold, or roll back

- All gates green for the full ~4h hold → next step on the ladder (respecting the
  peak-window carve-out for the 25%/50% steps).
- Gate failure → [`pr4-app-engine-rollback-runbook.md`](pr4-app-engine-rollback-runbook.md)
  class (a) (weights back to `app_engine=100`), then diagnose.
- Record every step (weights, `$STEP_START`, gate outputs, scale-out count, anomalies)
  in `docs/migration/history/` when the ramp campaign completes.

## Accepted risk with alerts dropped

With Stage 6 item 4 dropped there is no unattended detection: a regression that starts
mid-hold goes unnoticed until the next manual sweep. During holds, run the step-3 5xx
sweep at least every few waking hours; the 4h holds are sized to be attended
end-to-end. **Re-open condition:** if this cadence proves unsustainable, implement the
dropped alerts (three policies, ~$1.50/mo once Google's alerting billing starts, $0
before then) rather than lengthening the sweep interval.

## Log-volume caveat (post-100%)

Full-rate LB request logging at production volume (~26M req/month) may exceed the
logging free tier. After the 100% step stabilizes, revisit: either accept the logging
cost or reduce `logConfig.sampleRate` — but a reduced sample rate means log-derived
counts are no longer exact, and these gates (if still in use) should move to Monitoring
metrics, which are free and always-on.
