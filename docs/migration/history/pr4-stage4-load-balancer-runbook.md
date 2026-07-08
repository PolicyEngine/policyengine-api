# PR 4 Stage 4 Runbook: Provision the Load Balancer

> Per-stage record: gcloud equivalents of every console action, committed **before**
> manual execution (the plan's infra rule). Current operational behavior:
> [`../cloud-run-operations.md`](../cloud-run-operations.md). Source of truth for stage
> gates: the Stage 4 section of `api-v1-pr4-cloud-run-host-cutover-execution-plan.md`
> in the planning folder.

Builds the global external Application Load Balancer (`EXTERNAL_MANAGED`) that will
eventually front `api.policyengine.org`, with two serverless NEG backends (App Engine,
Cloud Run) and a weighted URL map pinned to **app_engine=100 / cloud_run=0**. This stage
creates infrastructure only — **no DNS change to `api.policyengine.org`** (the only DNS
edits are the two certificate-authorization CNAMEs; the `api-lb` validation hostname is
Stage 5, the real cutover is Stage 8).

Facts baked in from pre-checks (2026-07-08):

- `api.policyengine.org` currently CNAMEs to `ghs.googlehosted.com`, which serves **both
  A and AAAA** — IPv6 clients exist today, so the LB gets dual (IPv4 + IPv6) frontends.
- The App Engine app's `locationId` is `us-central` → serverless NEGs go in compute
  region **`us-central1`** (same region as the Cloud Run service).
- Executor needs `roles/compute.loadBalancerAdmin` + `roles/certificatemanager.editor`
  (or owner) on `policyengine-api`; the CI deploy service account has neither and never
  will — this stage is manual by design.

## 0. Shell variables (paste first)

```bash
export PROJECT=policyengine-api REGION=us-central1
export IP4=policyengine-api-lb-ip IP6=policyengine-api-lb-ipv6
export NEG_GAE=neg-app-engine NEG_CR=neg-cloud-run
export BS_GAE=bs-app-engine BS_CR=bs-cloud-run
export MAP=lb-api REDIRECT_MAP=lb-api-redirect
export PROXY_HTTPS=proxy-api-https PROXY_HTTP=proxy-api-http
export CERT=cert-api-lb CERT_MAP=map-api
```

## 1. Static IPs

```bash
gcloud compute addresses create "$IP4" --project "$PROJECT" --global --ip-version=IPV4
gcloud compute addresses create "$IP6" --project "$PROJECT" --global --ip-version=IPV6
gcloud compute addresses list --project "$PROJECT" --global \
  --format 'table(name, address)'   # record BOTH in this file when executed
```

Executed values: `IP4 = ______` / `IP6 = ______` (fill in at execution).

## 2. Certificate via DNS authorization (both hostnames)

```bash
for D in api api-lb; do
  gcloud certificate-manager dns-authorizations create "auth-${D}" \
    --project "$PROJECT" --domain "${D}.policyengine.org"
done
gcloud certificate-manager dns-authorizations list --project "$PROJECT" \
  --format 'table(name, dnsResourceRecord.name, dnsResourceRecord.data)'
```

Add the two CNAME records printed above **at Squarespace** (they look like
`_acme-challenge.api.policyengine.org → xxxx.authorize.certificatemanager.goog`).
These are additive records — they do not affect serving DNS. Then:

```bash
gcloud certificate-manager certificates create "$CERT" --project "$PROJECT" \
  --domains="api.policyengine.org,api-lb.policyengine.org" \
  --dns-authorizations="auth-api,auth-api-lb"
gcloud certificate-manager maps create "$CERT_MAP" --project "$PROJECT"
for D in api api-lb; do
  gcloud certificate-manager maps entries create "entry-${D}" --project "$PROJECT" \
    --map "$CERT_MAP" --hostname "${D}.policyengine.org" --certificates "$CERT"
done
# GATE (may take minutes after the CNAMEs propagate):
gcloud certificate-manager certificates describe "$CERT" --project "$PROJECT" \
  --format 'value(managed.state, managed.authorizationAttemptInfo)'
# expect state ACTIVE and both domains AUTHORIZED before proceeding to step 5.
```

## 3. Serverless NEGs

```bash
gcloud compute network-endpoint-groups create "$NEG_GAE" --project "$PROJECT" \
  --region "$REGION" --network-endpoint-type=serverless --app-engine-service=default
gcloud compute network-endpoint-groups create "$NEG_CR" --project "$PROJECT" \
  --region "$REGION" --network-endpoint-type=serverless --cloud-run-service=policyengine-api
```

Pinning `--app-engine-service=default` is deliberate: the NEG routes straight to the
service, **bypassing `gcp/dispatch.yaml`** — the dispatch file stays as the rollback
path for the direct App Engine domain mapping, not part of the LB path.

## 4. Backend services (timeout 600, full request logging)

```bash
for PAIR in "$BS_GAE:$NEG_GAE" "$BS_CR:$NEG_CR"; do
  BS="${PAIR%%:*}"; NEG="${PAIR##*:}"
  gcloud compute backend-services create "$BS" --project "$PROJECT" --global \
    --load-balancing-scheme=EXTERNAL_MANAGED --protocol=HTTPS \
    --timeout=600 --enable-logging --logging-sample-rate=1.0
  gcloud compute backend-services add-backend "$BS" --project "$PROJECT" --global \
    --network-endpoint-group="$NEG" --network-endpoint-group-region="$REGION"
done
```

`--timeout=600`: the default 30s would kill long `/calculate` requests; Cloud Run's own
request cap is 300s and App Engine's is longer, so 600 makes the LB never the binding
constraint. **Validated empirically in Stage 5's long-request proof** — if the timeout
turns out not to be honored for serverless NEGs, that gate catches it before any DNS
change. Reminder: serverless NEGs have **no health checks** — alerting (Stage 6) is the
failover mechanism.

## 5. URL map at 100/0, proxies, forwarding rules

```bash
gcloud compute url-maps create "$MAP" --project "$PROJECT" \
  --default-service "$BS_GAE"
gcloud compute url-maps export "$MAP" --project "$PROJECT" \
  --destination /tmp/lb-api.yaml
```

Edit `/tmp/lb-api.yaml`: replace the top-level `defaultService: ...` line with the
weighted action (weights are the ramp lever for Stages 9–11):

```yaml
defaultRouteAction:
  weightedBackendServices:
  - backendService: https://www.googleapis.com/compute/v1/projects/policyengine-api/global/backendServices/bs-app-engine
    weight: 100
  - backendService: https://www.googleapis.com/compute/v1/projects/policyengine-api/global/backendServices/bs-cloud-run
    weight: 0
```

```bash
gcloud compute url-maps import "$MAP" --project "$PROJECT" --source /tmp/lb-api.yaml --quiet
```

Then the HTTPS side (certificate map attaches to the proxy — no `--ssl-certificates`):

```bash
gcloud compute target-https-proxies create "$PROXY_HTTPS" --project "$PROJECT" \
  --url-map "$MAP" --certificate-map "$CERT_MAP"
for PAIR in "fr-api-https:$IP4" "fr-api-https-v6:$IP6"; do
  FR="${PAIR%%:*}"; ADDR="${PAIR##*:}"
  gcloud compute forwarding-rules create "$FR" --project "$PROJECT" --global \
    --load-balancing-scheme=EXTERNAL_MANAGED --address="$ADDR" \
    --target-https-proxy="$PROXY_HTTPS" --ports=443
done
```

HTTP→HTTPS 301 (separate redirect map; `url-maps create` has no redirect flags, so
import it):

```bash
cat > /tmp/lb-api-redirect.yaml <<'YAML'
name: lb-api-redirect
defaultUrlRedirect:
  httpsRedirect: true
  redirectResponseCode: MOVED_PERMANENTLY_DEFAULT
  stripQuery: false
YAML
gcloud compute url-maps import "$REDIRECT_MAP" --project "$PROJECT" \
  --source /tmp/lb-api-redirect.yaml --quiet
gcloud compute target-http-proxies create "$PROXY_HTTP" --project "$PROJECT" \
  --url-map "$REDIRECT_MAP"
for PAIR in "fr-api-http:$IP4" "fr-api-http-v6:$IP6"; do
  FR="${PAIR%%:*}"; ADDR="${PAIR##*:}"
  gcloud compute forwarding-rules create "$FR" --project "$PROJECT" --global \
    --load-balancing-scheme=EXTERNAL_MANAGED --address="$ADDR" \
    --target-http-proxy="$PROXY_HTTP" --ports=80
done
```

## 6. Snapshot the URL map (audit trail for every future weight change)

```bash
mkdir -p docs/migration/urlmap
gcloud compute url-maps export "$MAP" --project "$PROJECT" \
  --destination "docs/migration/urlmap/$(date -u +%Y%m%dT%H%M%SZ)-lb-api.yaml"
git add docs/migration/urlmap/ && git commit -m "Snapshot LB URL map (Stage 4 initial, 100/0)"
```

All future weight changes follow the procedure in
[`../cloud-run-operations.md`](../cloud-run-operations.md) ("URL map weight changes"):
export → diff → edit → import → commit. Console clicks leave no audit trail, and
`url-maps import` **replaces the whole map** — always diff first.

## Exit gates (from the plan; evaluate before Stage 5)

```bash
LB_IP=$(gcloud compute addresses describe "$IP4" --project "$PROJECT" --global --format 'value(address)')
curl -sv --resolve "api.policyengine.org:443:${LB_IP}" \
  https://api.policyengine.org/liveness-check -o /dev/null 2>&1 \
  | grep -E "HTTP/|x-policyengine-backend"
# expect: 200 + X-PolicyEngine-Backend: app_engine  (traffic reaches GAE through the LB)
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' "http://${LB_IP}/liveness-check" \
  -H 'Host: api.policyengine.org'
# expect: 301 → https://api.policyengine.org/liveness-check
```

- Cert `state: ACTIVE`, both hostnames `AUTHORIZED` (step 2).
- LB request logs visible in Logging with `resource.type="http_load_balancer"` and
  `backend_service_name` populated (allow a few minutes after first traffic).
- IPv6 spot check: repeat the `--resolve` curl against the IPv6 address.

## Teardown (full rollback of this stage; reverse order)

```bash
gcloud compute forwarding-rules delete fr-api-https fr-api-https-v6 fr-api-http fr-api-http-v6 --global --project "$PROJECT" --quiet
gcloud compute target-https-proxies delete "$PROXY_HTTPS" --project "$PROJECT" --quiet
gcloud compute target-http-proxies delete "$PROXY_HTTP" --project "$PROJECT" --quiet
gcloud compute url-maps delete "$MAP" "$REDIRECT_MAP" --project "$PROJECT" --quiet
gcloud compute backend-services delete "$BS_GAE" "$BS_CR" --global --project "$PROJECT" --quiet
gcloud compute network-endpoint-groups delete "$NEG_GAE" "$NEG_CR" --region "$REGION" --project "$PROJECT" --quiet
gcloud compute addresses delete "$IP4" "$IP6" --global --project "$PROJECT" --quiet
# certificate-manager resources can stay (no cost, reusable) or be deleted last.
```

No serving-path risk at any point in this stage: nothing resolves to the LB until the
Stage 5 `api-lb` record, and `api.policyengine.org` continues to point at App Engine
until Stage 8. Standing cost while provisioned: ~$0.025/h per forwarding rule
(4 rules ≈ $73/month) plus egress — starts as soon as step 5 completes.
