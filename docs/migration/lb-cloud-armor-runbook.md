# Cloud Armor rate-limiting runbook

Repeated-use runbook for managing Cloud Armor security policies on a load
balancer's backend services: creating throttle rules safely (preview first),
deciding when to enforce them, tuning, and rolling back. The authoritative
record of what is currently deployed is the newest exported snapshot in
`docs/migration/armor/` — this document describes procedure, not state.

## Current deployment (summary — see newest snapshot for truth)

| | |
|---|---|
| Policy | `pol-api-lb`, attached to the Cloud Run backend service of the public API load balancer |
| Rules | Per-IP throttles on the metadata and calculate path families (1000, 1100; thresholds in the snapshot); a bearer-token exemption from them (900); a 403 for requests without `Authorization` outside the Public API's public routes (770–800) |
| Mode | metadata rule **ENFORCED** 2026-07-21 (worst legit observed 5/min vs 30 threshold — 6× headroom); calculate rule **ENFORCED** by the 2026-11-10 snapshot (it was still in preview on 2026-08-30, when observed legit/partner clients ran 39–88/min there); rules 900 and 770–800 enforced |

Note on preview validation: Cloud Armor **throttle** rules in preview only ever
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
   (matched and logged, never enforced) and is enforced only after the checks
   below.
4. **Rate limits address volume abuse, not expensive-request abuse.** A
   handful of heavy requests that saturate capacity sits below any threshold
   that spares real users — that is a capacity/scaling problem, not a Cloud
   Armor problem.
5. Cloud Armor's CEL `.matches()` regex rejects capture groups — use
   non-capturing `(?:...)`.

## Known caveat

Cloud Armor only sees traffic that crosses the load balancer. Serverless
default URLs (`*.run.app`) bypass it entirely, including rule 800's refusal of
requests without a credential; the Public API refuses those itself. This is
acceptable while ingress must stay open for CI smoke tests; revisit when
ingress is locked down to the LB.

## Requests that carry a bearer token (rule 900)

Since 2026-11-10, rule 900 lets requests to the metadata and calculate path
families skip the per-IP throttles in rules 1000 and 1100 when their
`Authorization` header is one well-formed bearer value
(`^[Bb]earer [A-Za-z0-9._~+/-]+=*$`). It exists because PolicyEngine's own
server routes on Vercel (www.policyengine.org's dashboard API and
app.policyengine.org's route) send every browser's request to the Public
API from a few Vercel addresses, which per-IP limits would count as one
client. Those routes apply their own per-browser limits on Vercel.

- **Why it is safe to skip the throttle:** the Public API checks every
  `Authorization` header before routing (PolicyEngine/policyengine-api#4237)
  and answers any that is not a valid credential with a small 401, so a
  made-up token is not served. Apply rule 900 only while that check is
  deployed.
- **Why the exact pattern:** the Public API treats a blank `Authorization`
  header as no credential, so a rule that only checked the header's presence
  would let blank headers skip the throttle (and, before 2026-11-17, be
  served). Two headers reach Cloud Armor joined by a comma, which the pattern
  rejects.
- **What it gives up:** requests with made-up tokens are not capped at the
  load balancer, though each costs the Public API one signature check. Before
  the Public API refused requests without a server credential (2026-11-17), a
  signed-in user's own valid token in `Authorization` also skipped the
  throttle and was served; since then the Public API refuses it outside its
  public routes.

Check it with requests of your own: 40 requests a minute to
`/us/metadata` with `Authorization: Bearer made-up` should all get 401 and
none 429, and the load balancer log should show
`jsonPayload.enforcedSecurityPolicy.priority=900`. Roll it back with
`gcloud compute security-policies rules update 900 --preview` (back to
log-only) or `rules delete 900`, then export a snapshot.

## Requests without a credential (rules 770–800)

Since 2026-11-17 the Public API runs with
`PUBLIC_API_SERVER_CREDENTIAL_REQUIRED=1`: it refuses every request without a
server credential with 401 before routing, except its public routes. Since the
same day, rule 800 refuses at the load balancer, with 403, the requests among
those that carry no `Authorization` header or a blank one (only spaces and
tabs). Rules 770–772 allow the public routes first:

| Priority | Action | Matches |
|---|---|---|
| 770 | allow | `GET` and `HEAD /health` |
| 771 | allow | `GET /v2/openapi.json` |
| 772 | allow | CORS preflights: `OPTIONS` with `Origin` and `Access-Control-Request-Method` |
| 800 | `deny(403)` | `!has(request.headers['authorization']) \|\| request.headers['authorization'].matches('^[[:blank:]]*$')` |

Rule 800 refuses only requests the Public API would refuse anyway, so they
no longer reach Cloud Run.

- **What callers see:** Cloud Armor can only deny with 403, 404 or 502, and
  its 403 is Google's HTML page. Through `api.policyengine.org`, a request
  without a credential gets that page, not the Public API's 401 with
  `WWW-Authenticate: Bearer` and a JSON body. Requests sent to the `*.run.app`
  URLs skip the load balancer and get the Public API's 401.
- **Tokens:** Cloud Armor can't validate a token, so any non-blank
  `Authorization` header passes rule 800 and the Public API checks it. A
  made-up token still gets the Public API's 401.
- **Keep the allow rules matched to the Public API.** Rules 770–772 copy
  `PUBLIC_ROUTES` and `is_public_request` in
  `policyengine_api/request_caller.py`. A route made public there must be
  allowed here before rule 800, or the load balancer refuses it.
- **Apply rule 800 only while enforcement is on.** With
  `PUBLIC_API_SERVER_CREDENTIAL_REQUIRED` off, the Public API serves requests
  without a credential, and rule 800 would refuse them.
- **Preflights and the throttles:** rule 772 matches before rules 1000 and
  1100, so CORS preflights to the metadata and calculate paths no longer count
  toward those per-address limits. The Public API's CORS middleware answers a
  preflight without running a route.
- **The blank pattern:** Cloud Armor refused `'^[ \t]*$'` with "Invalid
  Argument"; the POSIX class `'^[[:blank:]]*$'` (space or tab) is accepted.

Rule 800 ran in preview for 2 hours before it was enforced, shorter than the
24 hours under "Preview-to-enforcement checks", by decision. It logged 264
would-be refusals, and the Public API had answered every one of them with 401.
Unlike throttle rules, a deny rule in preview logs `DENY` in
`jsonPayload.previewSecurityPolicy.outcome`, so preview hits can be counted
directly.

Check it with requests of your own, without a credential, to
`api.policyengine.org`: `/`, `/us/metadata`, `POST /us/calculate` and `/v2/me`
get 403 with `text/html`; `GET` and `HEAD /health`, `/v2/openapi.json` and a
CORS preflight get 200; `Authorization: Bearer made-up` gets the Public API's
401. The load balancer log shows `jsonPayload.enforcedSecurityPolicy.priority=800`
with outcome `DENY` for the refused requests. Roll it back with
`gcloud compute security-policies rules update 800 --preview` (back to
log-only, within minutes) or `rules delete 800`, then export a snapshot. Rules
770–772 can stay; deleting 772 puts preflights back under the throttles.

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

### Preview-to-enforcement checks

Enforce a rule only when BOTH hold:

1. **Preview observation (≥24h, spanning the traffic pattern the rule
   targets — e.g. an overnight bot window):** LB log entries carry
   `jsonPayload.previewSecurityPolicy` (`name`, `outcome`). Group would-be
   throttle hits by client IP network, user agent, and path. Requirement: **zero
   hits from monitors, app-referred traffic, or polling clients; hits present
   on the abusive sources the rule targets.**
2. **Empirical threshold check:** from ≥7 days of LB logs, compute the per-IP
   peak request rate over the rule's interval for the matched path family,
   split legitimate vs other. Requirement: **worst legitimate rate ≤ half the
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
