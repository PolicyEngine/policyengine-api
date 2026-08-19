# Cloud Armor rate-limiting runbook

Repeated-use runbook for managing Cloud Armor security policies on a load
balancer's backend services: creating throttle rules safely (preview first),
deciding when to enforce them, tuning, and rolling back. The authoritative
record of what is currently deployed is the newest exported snapshot in
`docs/migration/armor/` — this document describes procedure, not state.

## Current deployment (summary — see newest snapshot for truth)

| | |
|---|---|
| Policy | `pol-api-lb`, attached to both backend services of the public API LB |
| Rules | Per-IP throttles on the metadata and calculate path families; thresholds in the snapshot |
| Mode | metadata rule **ENFORCED** 2026-07-21 (worst legit observed 5/min vs 30 threshold — 6× headroom); calculate rule **stays in preview at 75/60s** — observed legit/partner clients run 39–88/min there, so enforcing would 429 real use (incl. the partner API fallback) |

Note on the preview gate: Cloud Armor **throttle** rules in preview only ever
log `CONFORM` (never `EXCEEDED`), so the `previewSecurityPolicy` outcome field
cannot be used to count would-be-throttled requests. Judge a throttle rule's
enforcement readiness from **raw per-IP request-rate analysis of LB logs**, not
from preview outcome counts.

Origin: overnight bot waves saturated backends / churned autoscaling
(2026-07-13 → 2026-07-21 incidents; details in the cutover execution plan).

## Design principles

1. **Only throttle path families the frontends never poll.** Client apps poll
   some endpoints at ~1 req/s per session (society-wide calculation status,
   report status), and NAT'd offices aggregate many users onto one client IP.
   A per-IP rule that matches a polled path will 429 legitimate sessions —
   that is a design error, not a threshold-tuning problem. Before adding any
   rule, check the frontend code and LB logs for polling behavior on the
   matched paths.
2. **No blanket rules, no ban actions.** Throttling (429 per excess request)
   self-heals the moment a client slows down; bans amplify any false positive.
3. **Preview first, always.** Every new or changed rule starts in preview
   (matched and logged, never enforced) and graduates only through the gates
   below.
4. **Rate limits address volume abuse, not expensive-request abuse.** A
   handful of heavy requests that saturate capacity sits below any threshold
   that spares real users — that is a capacity/scaling problem, not a Cloud
   Armor problem.
5. Cloud Armor's CEL `.matches()` regex rejects capture groups — use
   non-capturing `(?:...)`.

## Known caveat

Cloud Armor only sees traffic that crosses the load balancer. Serverless
default URLs (`*.run.app`, `*.appspot.com`) bypass it entirely. This is
acceptable while ingress must stay open for CI smoke tests; revisit when
ingress is locked down to the LB.

## Procedures

Set once per shell:

```sh
PROJECT=<project-id>
POLICY=<policy-name>
BACKENDS="<backend-service> [<backend-service> ...]"
```

### Create a policy and attach it

```sh
gcloud compute security-policies create $POLICY --project=$PROJECT \
  --description="<why>. See docs/migration/lb-cloud-armor-runbook.md"

for BS in $BACKENDS; do
  gcloud compute backend-services update $BS \
    --security-policy=$POLICY --global --project=$PROJECT
done
```

Immediately after attaching: verify serving is unaffected (sampled curls
against the public hostname, uptime monitor green, one live-suite run).

### Add a per-IP throttle rule (in preview)

```sh
gcloud compute security-policies rules create <priority> \
  --project=$PROJECT --security-policy=$POLICY \
  --expression="request.path.matches('<RE2 without capture groups>')" \
  --action=throttle \
  --rate-limit-threshold-count=<n> --rate-limit-threshold-interval-sec=<secs> \
  --conform-action=allow --exceed-action=deny-429 --enforce-on-key=IP \
  --preview
```

### Snapshot after every policy change

```sh
gcloud compute security-policies export $POLICY --project=$PROJECT \
  --file-name=docs/migration/armor/$(date -u +%Y%m%dT%H%M%SZ)-$POLICY.yaml
```

Commit the snapshot (mirrors the `urlmap/` convention).

### Preview → enforce gates

Enforce a rule only when BOTH hold:

1. **Preview observation (≥24h, spanning the traffic pattern the rule
   targets — e.g. an overnight bot window):** LB log entries carry
   `jsonPayload.previewSecurityPolicy` (`name`, `outcome`). Group would-be
   throttle hits by client IP network, user agent, and path. Gate: **zero
   hits from monitors, app-referred traffic, or polling clients; hits present
   on the abusive sources the rule targets.**
2. **Empirical threshold check:** from ≥7 days of LB logs, compute the per-IP
   peak request rate over the rule's interval for the matched path family,
   split legitimate vs other. Gate: **worst legitimate rate ≤ half the
   threshold.**

```sh
gcloud compute security-policies rules update <priority> \
  --project=$PROJECT --security-policy=$POLICY --no-preview
```

Snapshot and commit; verify on the next abuse wave: 429s appear in LB logs
(`jsonPayload.enforcedSecurityPolicy.outcome="DENY"`), autoscaler churn and
monitor incidents stop.

If a legitimate source shows up in preview hits: raise the threshold
(`rules update <priority> --rate-limit-threshold-count=<n>`), stay in
preview, restart the observation window.

### Tuning / rollback

- Change a threshold: `rules update <priority> --rate-limit-threshold-count=<n>`
  (snapshot after).
- Disable enforcement fast: `rules update <priority> --preview` (back to
  log-only; propagates in minutes).
- Full detach: `gcloud compute backend-services update <backend-service>
  --security-policy="" --global --project=$PROJECT` per backend service. The
  policy remains, unattached.

## Cost

Standard tier, pay-as-you-go: $5/policy/mo + $1/rule/mo + $0.75/M requests
evaluated (global policies; verified against the Billing Catalog API
2026-07-21). Order-of-magnitude ~$10/mo for one policy with a few rules at
sub-million monthly request volume.
