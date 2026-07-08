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
