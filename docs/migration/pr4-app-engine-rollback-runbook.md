# PR 4 Rollback Runbook: returning traffic to App Engine

> Live operational document during the ramp campaign. Three rollback classes, fastest
> first. **Class (a) is the failover mechanism for this architecture**: serverless NEGs
> have no LB health checks, so nothing fails over automatically — a human runs (a).
> Weight-change mechanics: [`cloud-run-operations.md`](cloud-run-operations.md)
> ("URL map weight changes").

## Which class for which symptom

| Symptom | Class |
|---|---|
| 5xx / latency regression on the Cloud Run path; failed ramp gate; Cloud Run capacity or scaling trouble | **(a)** weights |
| Bad application release (breaks both backends — same code deploys to both) | **(a)** first if Cloud-Run-skewed, then **(b)** GAE version rollback |
| LB-layer failure: cert expiry/misissue, forwarding-rule or URL-map misconfiguration that can't be fixed forward in minutes | **(c)** DNS — last resort, time-boxed |

## Class (a) — primary: URL-map weights → App Engine 100/0 (~minutes)

Export → edit → import per the ops-doc procedure (abbreviated here for speed; diff
against the last snapshot when time permits, skip when firefighting):

```bash
gcloud compute url-maps export lb-api --project policyengine-api \
  --destination /tmp/rollback.yaml --quiet
# edit: bs-app-engine weight → 100, bs-cloud-run weight → 0
gcloud compute url-maps import lb-api --project policyengine-api \
  --source /tmp/rollback.yaml --quiet
gcloud compute url-maps describe lb-api --project policyengine-api \
  --format 'yaml(defaultRouteAction)'
```

- Control plane applies immediately; **GFEs follow over ~5–10 min** (observed Stages
  4–5). Verify with header sampling, not `describe`:

```bash
for i in $(seq 1 200); do
  curl -sI --max-time 10 https://api.policyengine.org/liveness-check | tr -d '\r' \
    | awk -F': ' 'tolower($1)=="x-policyengine-backend" {print $2}'
done | sort | uniq -c   # expect 200 app_engine after settle
```

- Afterward: commit a timestamped snapshot to `docs/migration/urlmap/`, sweep the LB
  logs for the incident window (filter `bs-*` backend names, not `aef-*`), and record
  the incident in `docs/migration/history/`.
- App Engine has served 100% until this campaign and is never scaled down during it
  (Stage 11 decommission happens only after the post-100% soak), so (a) needs no
  capacity preparation.

## Class (b) — App Engine version rollback (existing mechanism, unchanged)

For a bad application release rather than a path problem. Works regardless of LB
weights, since it acts on the GAE service behind `bs-app-engine`:

```bash
gcloud app versions list --project policyengine-api --service default \
  --sort-by '~version.createTime' | head   # identify last-good version
gcloud app services set-traffic default \
  --splits <LAST_GOOD_VERSION>=1 --project policyengine-api --quiet
```

Pair with class (a) so the rolled-back GAE version actually receives the traffic. Note
the Cloud Run side keeps serving the bad release until a fix-forward deploy — another
reason (a) accompanies (b).

## Class (c) — catastrophic: DNS back to pre-cutover records (time-boxed!)

Only for LB-layer failures that can't be fixed forward. Restore the pre-cutover
records at Squarespace (shape: `api` CNAME `ghs.googlehosted.com.`). Verbatim values
are deliberately NOT embedded here — get them from, in order:

1. **Authoritative, always current:** `gcloud app domain-mappings describe
   api.policyengine.org --project policyengine-api` (or App Engine console → Settings
   → Custom domains) — shows exactly the records App Engine expects. Valid until the
   domain mapping is deleted at Stage 11 decommission.
2. The pre-cutover capture (records + TTLs, taken at Stage 7) in the private migration
   planning folder.

Two clocks limit this option:

1. **TTL**: propagation is bounded by the TTL recorded at Stage 7 (Squarespace floor;
   expect ≥1h). Clients resolve back gradually, not at once.
2. **Certificate decay**: once DNS moves to the LB at Stage 8, App Engine's managed
   certificate for `api.policyengine.org` stops renewing. Record its expiry at cutover
   (typically ≤90 days out). **After that expiry, class (c) serves invalid TLS and is
   dead** — the only path is fixing the LB forward and using class (a).

After any (c) execution: the LB keeps running (no teardown under pressure); re-cutover
follows the Stage 8 procedure once the failure is understood.

## After any rollback

1. Snapshot + commit the URL map state (even for (b)/(c) — record what was serving).
2. Preserve evidence: LB log sweep and Cloud Run service logs for the incident window.
3. Write the incident record in `docs/migration/history/` before resuming the ramp;
   resume from step 1 of the ramp ladder gate sequence at the weight you rolled back
   from, not where you left off, if the cause was load-correlated.
