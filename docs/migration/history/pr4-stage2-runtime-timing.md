# PR 4 Stage 2: Runtime Timing & Capacity Qualification (2026-07-07)

> Per-stage record (lean protocol; see the Stage 2 section of
> `api-v1-pr4-cloud-run-host-cutover-execution-plan.md` in the planning folder).
> Raw per-cell JSONs: [`pr4-stage2-cells/`](pr4-stage2-cells/). Load generator:
> `scripts/measure_cloud_run_runtime.py` (closed-loop clients; `/us/calculate`
> cache-busted via top-level nonce — cached responses serve in ~260ms vs ~44s+
> engine time, so unbusted load tests measure Redis, not capacity).

All measurements from a single external vantage against `*.run.app` tag URLs
(no public traffic; DNS on App Engine throughout). Phase 0/A/B/C cells ran the
`stage3-prod-2407-864b0e5` image; the final soak ran `stage3-prod-2411-6c661ae`
after a mid-campaign CI promote (minor bundle-version delta; runtime shape
unchanged).

## Decisions

| Knob | Value | Basis |
|---|---|---|
| `WEB_CONCURRENCY` | **2** | w1 is 40–60% slower at 4 clients (calculate p50 137.7s vs 86.5s) and collapses at 8 clients where w2 stays healthy — two processes = two GILs on 4 vCPU. Memory fits (soak peak 69% of 16Gi). |
| Cloud Run `--concurrency` | **4** | c8 OOM-killed a worker in a 30-min soak (memory p95 92%, gunicorn `SIGKILL! Perhaps out of memory?`); c4 soaks clean (69% mem, zero OOM/5xx) — excess load queues at the platform and fails as client timeouts instead of dying in-instance. Must be **pinned explicitly in the deploy script** (see incidents). |
| min-instances | **1, service-level** | User-facing scale-from-zero wake measured at **282.8s** via the service URL — 17s under the 300s request timeout; a cold start on the request path can 504 real users. Service-level (not revision-level) per the Stage 3 tag/cost-bomb note. |
| max-instances | **4** | Peak real traffic 10.98 RPS (worst 5-min bucket, 7d) is dominated by light requests (48.5% economy job-polling, 22.2% calculate mostly Redis-cached, 14.6% metadata). Worst-case engine capacity ≈ 1–2 concurrent uncached calculates/instance; 4 instances gives ≥2× headroom for realistic uncached bursts. Cost note: 4 warm 16Gi instances is the ceiling only under load — min 1 warm otherwise. |
| Memory / CPU | **keep 16Gi / 4 vCPU** | c4 soak peaked at 69% (knife-edge vs the 70% gate). Mitigations recorded below rather than paying for 6 vCPU (forced by >16Gi) now; revisit if Stage 10 ramp watchpoints trip. |

## Phase 0 — free evidence

- **Cold starts** (mined from 7d of revision logs, n=18): p50 171.5s, p95 215.2s,
  range 133.5–216.8s. Tail is pre-cpu-boost revisions; post-boost ~161–168s.
  Live service-URL calibration: **282.8s** end-to-end (≈170s container boot +
  ≈110s scheduling/queue).
- **Traffic** (`appengine.googleapis.com/http/server/response_count`, 7d,
  5-min buckets, n=1244): peak 10.98 RPS, p99 3.66, p50 0.05. Endpoint mix
  (3,000-request nginx log sample, 3d): 48.5% `/economy` (job polling), 22.2%
  `/calculate` (mostly cache hits in practice), 14.6% `/metadata`, ~2% policy.
- **Memory pre-check**: promoted w1 revision p99 = 9% of 16Gi over 48h →
  2-worker feasibility confirmed cheaply (matrix pruned to one row).

## Phase A — warm parity (gate: per-probe CR p95 ≤ GAE p95 × 1.20, 0 errors)

First run **FAILED** at 3.25× — entirely `/us/metadata` (13.2s vs 4.3s):
starlette `GZipMiddleware` at default compresslevel 9 compressing the ~70MB
payload in-request (~5.5s of CPU measured on the real payload) vs nginx-side
gzip on GAE flex. Fixed by #3735 (compresslevel 4: 0.73s → 9.9MB, 7.5× faster
for ~10% larger output). Incidental finding, out of scope per maintainer:
`Accept-Encoding: identity` → 500 on Cloud Run (70MB raw exceeds the ~32MB
response cap); mooted by planned metadata slimming.

Re-run after the fix — **PASS**, CR beats GAE on every probe:

| p95 | Cloud Run | App Engine | ratio |
|---|---|---|---|
| liveness | 437ms | 723ms | 0.60 |
| readiness | 411ms | 617ms | 0.67 |
| us_metadata | 4,586ms | 6,457ms | 0.71 |

(Pooled-aggregate p95 across heterogeneous probes lands at 1.2005 — an
artifact of mixing probe classes; the plan's gate is per-probe.)

## Phases B/C — cells (10 min measured each; 30% calculate share, cache-busted)

calculate p50 (p95) seconds; † = collapse:

| clients | w1-c80 | w2-c8 | w2-c32 | w2-c80 (5-min) |
|---|---|---|---|---|
| 4 | 137.7 (163.3) | **86.5 (156.4)** | 100.9 (146.4) | 134.7 (151.2) |
| 8 | 239.8, 6/11 timeout | 172.4 (191.2), clean | 131.4 (252.2), 1 timeout | — |
| 16 | † 100% timeout | † 66/71 timeout | † 21× 5xx + 53 timeout | — |

Findings: (1) two workers materially outperform one — the GIL, not vCPU count,
is the binding constraint at low concurrency; (2) every config collapses at 16
clients on one instance — per-instance worst-case ceiling is ~4–8 mixed
clients (~1–2 concurrent uncached calculates); (3) at overload, low
`--concurrency` fails clean (platform queue timeouts) while high admits
requests that die in-instance as 5xx.

## Phase D — soaks (30 min, 8 clients)

| Config | mem p95 peak | cpu p95 peak | OOM | 5xx | Verdict |
|---|---|---|---|---|---|
| w2-c8 | **92%** | 91% | **worker SIGKILL 17:47:03** | 10 | **FAIL** |
| w2-c4 | 69% | 66% | none | none | **PASS** (66/66 calculates OK; 15 metadata client-timeouts = clean queueing at 2× admission) |

Sustained concurrent engine work grows the 2-worker working set far beyond the
5-minute honeymoon (45%) — admission control at c4 is what keeps the instance
memory-safe.

## Incidents (both anticipated by the plan, both handled)

1. **Mid-campaign CI promotes** (two `policyengine-release` dispatches on
   2026-07-07): cells unaffected (tag URLs pin revisions); final soak ran the
   newer image (noted above).
2. **Template pollution, realized**: CI deploys forked from a variant template
   and shipped candidates with inherited `containerConcurrency: 32` (CI's
   `--set-env-vars` wiped `WEB_CONCURRENCY`, but CI never sets
   `--concurrency`). No public traffic affected. Restored mid-campaign to an
   **explicit 80** — discovering that `--concurrency default` resolves to the
   *platform* default (now **640**), not the historical 80. Cleanup verified:
   all `s2-*` tags removed, variant revisions deleted (`s2-restore2` remains
   as the undeletable latest revision holding the clean template; supersedes
   on next CI deploy), serving traffic on the CI candidate throughout.

## Exit-gate mapping

- Warm parity ✓ (per-probe, post-#3735). Errors 0 over 10 reps ✓.
- Sustained ≥2× estimated peak ✓ for the realistic mix (peak 11 RPS is
  mostly cached/light; the synthetic 8-client cache-busted soak is far beyond
  2× realistic *engine* load and still met memory/error gates at c4). The
  1.5×-single-request p95 clause holds for the realistic mix, not for the
  synthetic worst case — which instead defines the per-instance ceiling used
  for max-instances.
- Memory < 70% after 30-min soak ✓ (69%, knife-edge — see follow-ups).
- Cold-start p95 quantified ✓ (215.2s mined; 282.8s user-facing). Values
  written down with numbers ✓ (this document).

## Follow-ups for Stage 3

1. Deploy script must pin `--concurrency 4` and `WEB_CONCURRENCY=2`
   explicitly (template pollution + the `default`=640 trap make implicit
   values untenable).
2. Service-level `min-instances 1` (manual, runbook) + unit invariant keeping
   revision-level at 0.
3. Consider gunicorn `--max-requests` + jitter (worker recycling) to cap the
   slow memory growth behind the 69% knife-edge.
4. Re-baseline after metadata slimming lands; it dominates warm-parity and
   transfer costs.
