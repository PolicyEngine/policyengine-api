# Cloud Armor rate-limiting runbook (lb-api)

Repeated-use runbook for the Cloud Armor security policy on the public API load
balancer. Created 2026-07-21 in response to overnight bot waves (2026-07-21
00:00–06:00Z: facebookexternalhit re-crawl wave + three scraper networks, bursts
to 893 req/30min in the traffic trough) that churned Cloud Run scale-outs
(1→4→1→4, 18 instance boots) — each ~3-min import boot queues early-bind-routed
requests, producing monitor timeouts and user-facing 504s, and (the prior week)
CPU-saturating the single App Engine instance.

## Shape

- **Policy:** `pol-api-lb` (Cloud Armor Standard, pay-as-you-go), project
  `policyengine-api`.
- **Attached to BOTH backend services** of URL map `lb-api`: `bs-app-engine` and
  `bs-cloud-run` — one policy protects both platforms at the edge.
- **Rules: targeted throttles only. No blanket rules, no bans.** The frontends
  poll `/economy/...` (society-wide calcs, 1 req/s per client while pending —
  `SocietyWideCalcStrategy.getRefetchConfig`) and `/report/{id}` (~1 req/s
  observed); NAT'd offices sum several users onto one client IP. Any rule whose
  match includes a polled path family will 429 legitimate sessions — treat that
  as a design error, not a tuning problem.

| Priority | Action | Match (CEL) | Per-IP limit | Rationale |
|---|---|---|---|---|
| 1000 | throttle → 429 | `request.path.matches('^/[a-z]{2}/metadata$')` | 30 / 60s | 10–11 MB CPU+transfer-heavy scrape target; fetched ~once per app session, never polled |
| 1100 | throttle → 429 | `request.path.matches('^/[a-z]{2}/calculate(?:-full)?$')` | 75 / 60s | Single-shot in app-v2 (no polling); generous headroom for NAT + retry storms (~24/min worst observed legit); catches single-IP hammering. NOTE: Cloud Armor regex rejects capture groups — use non-capturing `(?:...)` |
| 2147483647 | allow (default) | `*` | — | |

Deliberately NOT rate-limited: `/economy/`, `/report/`, `/simulation/`,
`/household/...` (polled or retry-prone app surfaces — a 429 there breaks a live
session) and scanner 404 paths (~150 ms each; no capacity impact). Per-IP
throttles barely touch facebookexternalhit (Meta spreads across many IPs in
2a03:2880::/29); the app-side malformed-payload 400 fix is the facebook-bot
mitigation.

## Known caveat

Cloud Armor only sees traffic that crosses the LB. The default
`*.run.app` / `*.appspot.com` URLs bypass it. Ingress deliberately stays open
through PR 4 (CI smoke tests need `*.run.app`); bots observed so far target
`api.policyengine.org`, so coverage is acceptable. Revisit at PR 17 (ingress
lockdown).

## Create (executed 2026-07-21; preview mode)

```sh
gcloud compute security-policies create pol-api-lb \
  --project=policyengine-api \
  --description="Rate limiting for api.policyengine.org (lb-api). See docs/migration/lb-cloud-armor-runbook.md"

gcloud compute security-policies rules create 1000 \
  --project=policyengine-api --security-policy=pol-api-lb \
  --expression="request.path.matches('^/[a-z]{2}/metadata$')" \
  --action=throttle \
  --rate-limit-threshold-count=30 --rate-limit-threshold-interval-sec=60 \
  --conform-action=allow --exceed-action=deny-429 --enforce-on-key=IP \
  --preview

gcloud compute security-policies rules create 1100 \
  --project=policyengine-api --security-policy=pol-api-lb \
  --expression="request.path.matches('^/[a-z]{2}/calculate(?:-full)?$')" \
  --action=throttle \
  --rate-limit-threshold-count=75 --rate-limit-threshold-interval-sec=60 \
  --conform-action=allow --exceed-action=deny-429 --enforce-on-key=IP \
  --preview

gcloud compute backend-services update bs-cloud-run  --security-policy=pol-api-lb --global --project=policyengine-api
gcloud compute backend-services update bs-app-engine --security-policy=pol-api-lb --global --project=policyengine-api
```

Post-attach verification: header-sampled curls (split unchanged, all 200),
BetterStack green, one live-suite run. Export a snapshot after every policy
change:

```sh
gcloud compute security-policies export pol-api-lb --project=policyengine-api \
  --file-name=docs/migration/armor/$(date -u +%Y%m%dT%H%M%SZ)-pol-api-lb.yaml
```

## Preview → enforce gates

Rules start in `--preview` (matched + logged, never enforced). Enforce a rule
only when BOTH hold:

1. **Preview observation (≥24h, must span an overnight bot window):** LB log
   entries carry `jsonPayload.previewSecurityPolicy` (`name`, `outcome`).
   Group would-be THROTTLE/DENY hits by client IP network, user agent, and
   path. Gate: **zero hits from monitor / app-referer / polling traffic; hits
   present on known scraper networks.**
2. **Empirical threshold check:** from ≥7 days of LB logs, compute the per-IP
   peak 60s request rate for each matched path family, split app-referer vs
   other. Gate: **worst legitimate rate ≤ half the rule's threshold.**

Enforce per rule with:

```sh
gcloud compute security-policies rules update 1000 \
  --project=policyengine-api --security-policy=pol-api-lb --no-preview
```

Then export + commit a new snapshot, and verify on the next bot wave: 429s in
LB logs (`jsonPayload.enforcedSecurityPolicy.outcome="DENY"`), Cloud Run
`instance_count` stays low overnight, no BetterStack incidents.

If a legitimate source appears in preview hits: raise that rule's threshold
(`rules update <prio> --rate-limit-threshold-count=<n>`), keep preview, restart
the observation window.

## Tuning / rollback

- Loosen/tighten a rule: `rules update <priority> --rate-limit-threshold-count=<n>`
  (snapshot after).
- Disable enforcement fast: `rules update <priority> --preview` (back to
  log-only; propagates in minutes).
- Full detach (the rollback): `gcloud compute backend-services update
  bs-cloud-run --security-policy="" --global --project=policyengine-api` (and
  same for `bs-app-engine`). The policy remains, unattached.

## Cost

Standard tier: $5/policy/mo + $1/rule/mo + $0.75/M requests (global policies).
At ~0.3–0.45M req/mo ≈ **$7.30/mo** for 1 policy + 2 rules. Verified against the
Billing Catalog API 2026-07-21.
