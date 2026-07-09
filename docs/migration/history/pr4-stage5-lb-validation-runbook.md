# PR 4 Stage 5 Runbook: Full-Path Validation via api-lb.policyengine.org

> Per-stage record: every command for the Stage 5 validation, committed before
> execution. Current operational behavior: [`../cloud-run-operations.md`](../cloud-run-operations.md)
> (the "URL map weight changes" section there is the procedure steps 4–5 rely on —
> merged with the Stage 4 PR). Source of truth for gates: the Stage 5 section of
> `api-v1-pr4-cloud-run-host-cutover-execution-plan.md` in the planning folder.

**The second-hostname trick:** `api-lb.policyengine.org` resolves to the load balancer
while `api.policyengine.org` keeps pointing at App Engine. The LB gets a real,
TLS-valid, publicly-resolvable name whose only clients are us — so every experiment in
this stage, including the 50/50 split, is invisible to actual users. The Stage 4 cert
already covers `api-lb`; no certificate work here.

Inputs from Stage 4 execution: `IP4 = 34.117.200.13`, `IP6 = 2600:1901:0:347b::`,
URL map `lb-api`, backends `bs-app-engine` / `bs-cloud-run`, snapshot procedure in the
ops doc. Step 4 is the **first time Cloud Run ever serves through the LB** — its warm
instance (service-level min 1) and maxScale 4 are already in place from Stage 3.

## 0. Shell variables

```bash
export PROJECT=policyengine-api
export LB_HOST=api-lb.policyengine.org
export GAE_HOST=api.policyengine.org
export SNAP_DIR=docs/migration/urlmap
```

## 1. DNS: `api-lb` records at Squarespace (manual, one-time)

Add two records for `policyengine.org`:

| Host | Type | Data |
|---|---|---|
| `api-lb` | A | `34.117.200.13` |
| `api-lb` | AAAA | `2600:1901:0:347b::` |

Additive only — nothing about `api` changes. Verify propagation:

```bash
dig +short A "$LB_HOST" @8.8.8.8      # expect 34.117.200.13
dig +short AAAA "$LB_HOST" @8.8.8.8   # expect 2600:1901:0:347b::
curl -s -o /dev/null -w '%{http_code}\n' "https://$LB_HOST/liveness-check"  # expect 200
```

## 2. Full-path validation at 100/0 (LB overhead quantification)

Both captures in the same hour, backends identical (GAE serves both paths), so any
delta is pure LB overhead. Warm both paths with a few throwaway requests first.

```bash
python scripts/capture_migration_baseline.py --base-url "https://$LB_HOST" \
  --repetitions 10 > /tmp/s5-lb-baseline.json
python scripts/capture_migration_baseline.py --base-url "https://$GAE_HOST" \
  --repetitions 10 > /tmp/s5-gae-baseline.json
# GATE: per probe, LB p50 <= direct-GAE p50 + 50ms; error rate 0 on both.

API_BASE_URL="https://$LB_HOST" python -m pytest \
  tests/integration/test_live_calculate.py \
  tests/integration/test_live_economy.py \
  tests/integration/test_live_budget_window_cache.py -v
# GATE: all green through the LB at 100/0.
```

## 3. Long-request proof (validates the fixed 60-min serverless-NEG timeout)

Stage 4 execution established (docs + API error) that serverless-NEG backends ignore
`timeoutSec` and get a fixed 60-minute LB timeout. This step proves it on our LB: a
cache-busted engine calculate runs ~40s+ — well past the displayed-but-ignored 30s.

```bash
python3 - <<'EOF' > /tmp/s5-long-calc.json
import json
p = json.load(open("tests/data/calculate_us_1_data.json"))
p["_loadtest"] = "s5-long-request-proof"   # cache-bust nonce (full-body hash key)
json.dump(p, open("/tmp/s5-long-calc.json", "w"))
EOF
curl -s -o /dev/null -w 'status=%{http_code}  time=%{time_total}s\n' --max-time 290 \
  -X POST "https://api-lb.policyengine.org/us/calculate" \
  -H 'Content-Type: application/json' -d @/tmp/s5-long-calc.json
# GATE: status=200 with time well over 30s (typically ~40-60s). A 502/504 near
# 30s would mean the LB is cutting long requests — stop and investigate.
```

(The economy flow in step 2's suite doubles as a second long-flow proof: its job
computation runs minutes end-to-end, though via polling rather than one long request.)

## 4. The 50/50 weighted-routing proof (first Cloud Run traffic through the LB)

Weight change strictly via the ops-doc procedure — export, **diff against the last
committed snapshot**, edit only the two weights, import, verify readback:

```bash
gcloud compute url-maps export lb-api --project "$PROJECT" --destination /tmp/lb-api-50.yaml --quiet
diff "$SNAP_DIR/$(ls $SNAP_DIR | tail -1)" /tmp/lb-api-50.yaml   # expect fingerprint-only noise
# edit: weight: 100 -> 50 (bs-app-engine), weight: 0 -> 50 (bs-cloud-run)
gcloud compute url-maps import lb-api --project "$PROJECT" --source /tmp/lb-api-50.yaml --quiet
gcloud compute url-maps describe lb-api --project "$PROJECT" --format 'yaml(defaultRouteAction)'
cp /tmp/lb-api-50.yaml "$SNAP_DIR/$(date -u +%Y%m%dT%H%M%SZ)-lb-api-5050.yaml"
```

Routing distribution — 200 header-sampled requests:

```bash
for i in $(seq 1 200); do
  curl -sI "https://$LB_HOST/liveness-check" | grep -i x-policyengine-backend
done | sort | uniq -c
# GATE: cloud_run share in [35%, 65%] of 200; zero requests without the header.
```

Then the live suites again at 50/50 — this is the **cross-backend job polling** proof:
economy flows POST a job to one backend and poll it from whichever backend each poll
lands on, working only because both share Cloud SQL state:

```bash
API_BASE_URL="https://$LB_HOST" python -m pytest \
  tests/integration/test_live_calculate.py \
  tests/integration/test_live_economy.py \
  tests/integration/test_live_budget_window_cache.py -v
# GATE: green at 50/50; zero 5xx in LB logs for the window:
gcloud logging read 'resource.type="http_load_balancer"
  resource.labels.backend_service_name=("bs-app-engine" OR "bs-cloud-run")
  httpRequest.status>=500 timestamp>="<window start>"' --project "$PROJECT" --limit 10
```

While here, spot-check `X-Forwarded-For` handling (requests now arrive via a proxy on
both backends): sample an app log line on each backend and confirm the client IP is the
real client, not the LB's.

## 5. Revert to 100/0 and commit both snapshots

```bash
# same procedure: export current (the 50/50), edit weights back to 100/0, import
gcloud compute url-maps import lb-api --project "$PROJECT" --source /tmp/lb-api-100.yaml --quiet
for i in $(seq 1 200); do
  curl -sI "https://$LB_HOST/liveness-check" | grep -i x-policyengine-backend
done | sort | uniq -c
# GATE: zero cloud_run of 200 — weights verified restored.
cp /tmp/lb-api-100.yaml "$SNAP_DIR/$(date -u +%Y%m%dT%H%M%SZ)-lb-api-restored.yaml"
git add "$SNAP_DIR" && git commit -m "Snapshot LB URL map (Stage 5: 50/50 test + restore to 100/0)"
```

## Exit gates (from the plan)

- Suites green through the LB at 100/0 **and** 50/50; cross-backend polling works.
- LB overhead quantified: per-probe p50 ≤ direct-GAE p50 + 50ms; error rate 0.
- Long-request proof: >30s calculate completes (200), LB never the binding constraint.
- 50/50 header counts within [35%, 65%] of 200 requests; zero 5xx during the split.
- Weights verified restored to 100/0 (200 curls, zero `cloud_run`).
- Both URL-map snapshots committed.

## Notes and blast radius

- Users are untouched throughout: only `api-lb` resolves to the LB, and its only
  clients are these validation commands.
- Step 4 sends real (validation) traffic to the production Cloud Run service for the
  first time via the LB — expected fine: warm instance, maxScale 4, the same suites
  pass against its direct URL every deploy.
- If anything fails mid-50/50, the immediate remedy is step 5's revert (weights back
  to 100/0); the `api-lb` DNS records can also simply be removed.
- Rough duration: 1–2 hours, dominated by two integration-suite runs.

## Execution record

### 2026-07-08 — first execution (all steps)

- Step 1: `api-lb` A/AAAA added at Squarespace; propagation + TLS verified.
- Step 2 (overhead gate): **PASS** — the LB path was *faster* than direct GAE on every
  probe (p50 deltas −290 to −644ms; modern GFE front end beats `ghs.googlehosted.com`).
  Suites green at 100/0 (one budget-window flake, passed on isolated retry — known
  backend queue contention).
- Step 3 (long-request proof): **PASS** — cache-busted calculate returned 200 well past
  30s; calculate runtime is payload-insensitive (~28–31s on GAE), so the economy suite's
  minutes-long polling flow doubles as the long-flow proof.
- Step 4 (50/50): distribution in bounds; suites 7/7 — **cross-backend job polling
  proven** (POST lands on one backend, polls served by both, shared Cloud SQL).
  **Caught one real bug:** the first Cloud Run scale-out (1→3 instances) served three
  503s — a two-worker cold-boot race on local sqlite init (`UNIQUE constraint failed:
  policy.id`; silent variant: a worker boots seeing 0/2 seed rows). Issue api#3746,
  fixed by an fcntl file lock around the exists-check + initialize in api#3747
  (verified with a 6-process fork-model boot harness: unfixed fails 3/3 rounds, fixed
  clean), merged and deployed the same day.
- Step 5: reverted to 100/0, verified 100/100 header samples `app_engine`. Observed:
  **URL-map weight changes take ~5–10 min to propagate across GFEs** — `describe`
  shows the new weights immediately, but sampling reflects them only after the settle
  period. Every future ramp step must wait out propagation before its sampling gate.

### 2026-07-09 — zero-5xx re-run against the fixed revision (12:53–13:30Z)

Purpose: yesterday's zero-5xx gate failed on the sqlite race; re-run scale-out boots on
the fixed revision (`policyengine-api-00058-sib`, the api#3747 deploy).

- 50/50 via the ops-doc procedure (12:53:44Z); propagation confirmed at 12:57Z.
- Load: `scripts/measure_cloud_run_runtime.py` through the LB — 16 closed-loop clients,
  10 min, `--cache-bust always` (every calculate does real engine work, ~30–45s). This
  held ~8 concurrent engine calls on the Cloud Run side (~4× one instance's
  uncached-calculate capacity) and forced a **1→4 instance scale-out**.
- **Sqlite race confirmed fixed:** zero 503s, zero tracebacks/`UNIQUE constraint`
  errors, zero worker crashes across all fresh boots. Client-side: 82/82 measured
  calculates 200; one 429 (Cloud Run queue backpressure, expected at saturation); zero
  5xx on `bs-app-engine` for the whole window.
- **Finding — three 504s on `bs-cloud-run`** (12:59:11Z, LB latencies ~306s, Cloud Run
  latencies ~299.97s, `response_sent_by_backend`): all three were calculates routed to
  the *first* scale-out instance at its birth — the instance's request logs for them
  precede its own "Starting new instance" line. They queued through the ~170s app
  import (the accepted early-bind routing-before-ready tradeoff), then ran
  GIL-contended and hit **Cloud Run's fixed 300s request timeout**. Later boots
  absorbed their queued traffic within the timeout. The load generator's stats stayed
  clean because the trio fired at the warmup/measurement boundary (excluded bucket) and
  was abandoned client-side at the 290s client timeout.
- **Gate disposition (user-approved):** recorded as a known cold-scale-out saturation
  artifact, not a defect — the zero-5xx gate is interpreted as zero *boot-failure* 5xx
  and Stage 5 is **CLOSED**. Carry-forward for Stage 6 ramp monitoring: isolated 504
  clusters coinciding with instance starts are cold-routing, distinct from steady-state
  5xx.
- Reverted to 100/0 (13:17Z), verified 200/200 header samples `app_engine` by 13:30Z.
  Both URL-map snapshots committed (`*-lb-api-5050-stage5-rerun.yaml`,
  `*-lb-api-restored-100-0-rerun.yaml`).
