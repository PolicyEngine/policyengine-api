# Stage 12A: user accounts and v1-anchored user associations

Stage 12A saves app v3 users' work in the Public API database, whether or not
they are signed in. A signed-in user authenticates with Auth0 social sign-on;
a signed-out browser identifies itself with a random UUID it keeps. The
Public API turns either credential into a PolicyEngine user ID and writes that
ID onto every saved policy, household, simulation, and report. Saved records
point at the v1 artifacts the app already creates. At sign-in, the browser's
signed-out work moves into the signed-in account.

## Consumers

Only app v3 (the flagship shell in `policyengine-app-v2`) consumes these
routes. The legacy builder stays browser-only, signed in or not.

- **Signed out.** App v3 generates a random UUID once per browser
  (`crypto.randomUUID()`), keeps it, and sends it as
  `PolicyEngine-Unauthenticated-User: <uuid>` on every `/v2/me*` and
  `/v2/user-*` request made while signed out. Its saved reforms and reports
  are stored server-side under that browser's unauthenticated user.
- **Sign-in.** Right after sign-in, app v3 calls
  `POST /v2/me/upgrade?country_id=` with both the bearer token and the
  browser's header. The browser's signed-out work then belongs to the account
  (see "Conversion and merge"). Afterwards app v3 sends only the bearer token.
- **Account.** App v3 calls `GET /v2/me` on its account page.
- **Saved work.** App v3 reads and writes `/v2/user-policies` (its reforms)
  and `/v2/user-reports`. `/v2/user-households` and `/v2/user-simulations`
  have no app consumer yet.
- **Shared reports.** An app v3 report link carries the report's
  user-report ID. Whoever opens it, signed in, signed out, or another user,
  reads `GET /v2/shared-reports/{id}?country_id=` with no credential (see
  "Shared reports").

## User types and credentials

`users.user_type` is `standard` or `unauthenticated`.

- A **standard** user is backed by one or more verified sign-in identities.
  Every user that existed before this revision, including the Stage 10
  legacy-mapping users, is standard.
- An **unauthenticated** user belongs to one signed-out browser. Its `id` is
  the browser's UUID, and every other user column (`first_name`, `last_name`,
  `email`, `primary_country`) is NULL. Its timestamps work as usual.

The router-level authenticator (`NativeRouteDependencies.require_user`) turns
a request into a principal before query, path, and body validation (only a
body that is not parseable JSON is rejected, with 422, by FastAPI first):

| Request | Principal or response |
| --- | --- |
| `Authorization: Bearer <token>` | Validated as below; a valid user token is a `UserPrincipal`. The unauthenticated-user header is ignored. |
| No bearer token, `PolicyEngine-Unauthenticated-User: <canonical UUID>` | `UnauthenticatedPrincipal(user_id)`. Needs no Auth0 configuration. |
| No bearer token and no header, or a header that is not a canonical UUID | 401 with `WWW-Authenticate: Bearer` |

A canonical UUID is the lowercase, hyphenated form that
`crypto.randomUUID()` produces (`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`).
Uppercase, unhyphenated, braced, and `urn:uuid:` forms are rejected.

Bearer tokens are RS256 Auth0 access tokens for the Public API audience.
`libs/user_auth.py` validates them against `{issuer}.well-known/jwks.json` and
checks `iss` and `aud`. The decoder is ported from the Simulation Entrypoint.
For a bearer token:

- an invalid token: 401 with `WWW-Authenticate: Bearer error="invalid_token"`
  (an invalid token never falls back to the header);
- a machine-to-machine (`…@clients`) token: 403;
- authentication not configured, or signing keys unreachable: 503.

The type alias `AccountPrincipal = UserPrincipal | UnauthenticatedPrincipal`
flows from the routes through every service.

An unauthenticated principal never acts on a standard user. When its UUID
names a standard user (one converted from this browser, or anyone else's), the
request gets 401 with `WWW-Authenticate: Bearer` and the message "This
browser's saved work now belongs to a signed-in account; sign in to continue".
After a conversion, app v3 should sign the user in, or generate a new UUID to
start a new signed-out session.

CORS already allows every request header (`allow_headers=["*"]` in
`asgi_factory`), so browsers may send `PolicyEngine-Unauthenticated-User`
cross-origin; a unit test covers the preflight. OpenAPI publishes the header as
the `UnauthenticatedUser` API-key security scheme, an alternative to
`UserAccessToken`.

## Provisioning strategies

`services/v2/identity` selects an `AccountProvisioningStrategy` from the
principal's type (`account_provisioning_for`). Each strategy has
`find_in_session` (no writes), `resolve_in_session(..., country_id)` (may
provision), and `resolve_for_read_in_session`. `find_principal_user_in_session`,
`resolve_principal_user_in_session`, and
`resolve_principal_user_for_read_in_session` dispatch to it.

- **`StandardAccountProvisioning`** maps `(issuer, subject)` to `users.id`
  through `user_identities`. The first request of any kind, read or write,
  inserts a standard user (with `primary_country` from `country_id`) and the
  identity. A concurrent first request loses `UNIQUE(issuer, subject)`, rolls
  back its savepoint, and re-reads, so exactly one user is created.
  `last_seen_at` is written at most hourly. Email is stored only when
  `email_verified` is true; it is never unique and never used for linking. No
  legacy user is adopted implicitly.
- **`UnauthenticatedAccountProvisioning`** provisions only on a write. It
  inserts `users(id=<browser UUID>, user_type='unauthenticated')` with
  `ON CONFLICT (id) DO NOTHING`, then re-reads the row `FOR SHARE`. Concurrent
  first writes therefore create exactly one user. The share lock holds until
  the write commits, so a conversion at sign-in waits for the write, and a
  write waits for a conversion in progress and then sees its result. If the
  user was deleted between the insert and the re-read (by its own account
  deletion, or a merge at sign-in), the insert runs once more. A row that
  turns out to be standard gets the 401 above.

**Reads never provision an unauthenticated user.** An absent one behaves as a
user with no records: lists are empty, gets return 404, `GET /v2/me` returns
404, and `GET /v2/me/export` returns `user: null` with empty lists. Creates,
PATCH, and DELETE of association records are writes and provision it. PATCH
and DELETE on a record it does not own still return 404.

## Conversion and merge

`POST /v2/me/upgrade?country_id=us|uk` calls
`convert_unauthenticated_user_in_session(session, unauthenticated_user_id=...,
principal=..., country_id=...)` in one transaction. It first locks the
browser's `users` row `FOR UPDATE`, but only while that row is
unauthenticated: a standard user's row is never locked.

| State | Outcome | What happens |
| --- | --- | --- |
| The identity has no user yet; the browser's unauthenticated user exists | `converted` | The `user_identities` row (issuer, subject, verified email) is inserted pointing at the browser's `users.id`; the user becomes `standard` with `primary_country = country_id`. The ID is unchanged, so every association stays owned. |
| The identity already belongs to standard user S; the unauthenticated user exists | `merged` | Every row of `user_policies`, `user_household_associations`, `user_simulation_associations`, and `user_report_associations` owned by the unauthenticated user moves to S with its ID, contents, and timestamps unchanged; then the unauthenticated user is deleted. |
| No unauthenticated user with that ID | `none` | The identity's user is resolved, or provisioned, as on any request. |
| The ID names a standard user (already converted, or anyone else's) | `none` | That user is never touched; the identity's user is resolved as on any request. |

The association tables have no uniqueness involving the owner
(`client_ref` and its per-user constraints were removed), so a merge never
conflicts. Association IDs do not change, so a report's `user_policy_id` link
stays valid. `legacy_user_mappings` and `legacy_user_policy_mappings` belong
only to standard users and are untouched.

Concurrency on Postgres:

- Concurrent upgrades of one browser run one at a time behind the
  `FOR UPDATE` lock. The first converts (or merges); the rest find a standard
  user and return `none`.
- A first sign-in racing an upgrade, or two browsers upgrading into a new
  account at once, are reconciled by `UNIQUE(issuer, subject)`: the identity
  insert that loses merges into the winner's user instead.
- A signed-out write in progress holds its share lock, so the upgrade waits
  for it and then moves its record too. A signed-out write that starts during
  the upgrade waits and then gets 401 (converted) or starts a new
  unauthenticated user (merged).
- Deleting an unauthenticated account matches only `user_type =
  'unauthenticated'`, so a deletion racing a conversion never deletes the
  converted standard user.

## Security notes

- **The browser UUID is a bearer credential.** Whoever presents it acts as
  that browser's unauthenticated user. Keep it out of URLs (it travels only in
  the header) and out of logs. The Public API never logs it: unauthenticated
  provisioning and deletion log only `user_type`, the upgrade logs only its
  outcome, request logs carry the path without the query string and never the
  headers, and `UnauthenticatedPrincipal` and `ResolvedUser` keep the ID out
  of `repr`. Responses still include `user_id` and `id`, but only to the
  credential's owner.
- **An unauthenticated principal never acts on a standard user**, including
  the one its own browser converted into (see "User types and credentials").
- **Anyone can mint unauthenticated users.** Any new UUID creates one on its
  first write, without signing in. Only edge throttling bounds how fast one
  client can create users and rows: the proposed per-IP write throttle
  (`docs/migration/armor/proposed/20261012-pol-api-lb-stage-12a-user-writes.yaml`).
  The request and field bounds below limit what each write stores.

## What else changed

- **Ownership.** Request bodies and queries never accept `user_id`; the owner
  always comes from the credential. Another user's record returns 404.
- **v1 references.** Each association accepts a `legacy_*_id` (a country-scoped
  v1 database ID). A batched, read-only SQLAlchemy connector checks it against
  the v1 mapped models in a short transaction, closed before the v2
  transaction opens. A missing reference returns 422.
  - `user-policies` and `user-households` also accept the v2 `policy_id` or
    `household_id`. With only a legacy ID, the v2 reference is filled from
    `legacy_policy_mappings` / `legacy_household_mappings` when a mapping
    exists.
  - Changing the legacy ID re-resolves the v2 reference, or clears it.
  - `PATCH /v2/user-policies` also accepts `policy_id`, which must name a v2
    policy in the row's country. Supplied alone, it points the row at that
    policy and clears `legacy_policy_id`, so an edited reform keeps its saved
    ID, name and creation time. Supplied with `legacy_policy_id`, both are
    stored, and `policy_id` must be the mirror copy of that v1 policy when
    one exists.
  - `PATCH /v2/user-households` accepts `household_id` the same way: it must
    name a v2 household in the row's country; alone, it clears
    `legacy_household_id`; with `legacy_household_id`, both are stored, and
    it must be the copy of that v1 household when one exists.
  - `user-simulations` and `user-reports` accept only legacy IDs in 12A.
- **Stage 10 mirror rows.** A `user_policies` row with a
  `legacy_user_policy_mappings` entry returns 409 on PATCH and DELETE. The
  mirror projection now also records `legacy_policy_id`.
- **Request bounds.** Every `/v2/me*` and `/v2/user-*` write rejects a body
  over 256 KiB with 413. FastAPI reads and parses the whole JSON body before
  any dependency runs, so this check does not limit what is read or parsed;
  Cloud Run's 32 MiB request limit does. The check is a dependency that runs
  after authentication, so an oversized body gets 413 before any
  body-validation error is reported and before any service or database work,
  which bounds what can be stored. Caller fields are also bounded:
  `description` and `source_note` at 10,000 characters, report `provisions` at
  64 KiB serialized, and the report `validation` snapshot at 500 calibration
  matches and 200 scorecard programs, with bounded strings (64 to 1,024
  characters). `provenance` was already bounded (enumerated fields and a
  2,048-character `ref`). Every user-route float and JSON value also rejects
  NaN and Infinity with 422: Python's JSON parser accepts them but Postgres
  JSONB cannot store them.
- **Account editing.** `PATCH /v2/me` returns 403 ("Sign in to edit your
  account details.") for an unauthenticated principal.
- **Account deletion.** For a signed-in user, when the Management API is
  configured, `DELETE /v2/me` first reads the client secret from Secret
  Manager and obtains a Management token. If either fails, it returns 503 with
  nothing deleted. It then deletes the user's `legacy_user_mappings` rows
  (RESTRICT FK), then the user (identities and associations cascade), then the
  Auth0 user. A 401 from Auth0 drops the cached token and retries once with a
  fresh one. If the Auth0 call still fails after the data is gone, the route
  returns 502 and a retry is safe. The Management settings are read only for
  this route. For an unauthenticated user, `DELETE /v2/me` deletes the user and
  its associations, never builds the Auth0 client, and returns 204 even when
  the user does not exist.
- **Removed before release: browser imports.** The earlier design kept
  signed-out work in browser storage and copied it in at sign-in through
  `POST /v2/me/imports`, idempotent on a per-user `client_ref`. That route,
  its services, validators, types, response models, tests, and contract
  entries, the `client_ref` field on every association input and response,
  and the `client_ref` columns and their `UNIQUE(user_id, client_ref)`
  constraints are all gone. A request to the old import path now gets the
  v2 catch-all's 405.

The wire contract (fields, statuses, nested report types) is the Stage 12A HTTP
contract shared with `policyengine-app-v2`. The generated route inventory is in
`docs/engineering/migration-contracts.md`.

| Route | Signed in (bearer token) | Signed out (unauthenticated-user header) |
| --- | --- | --- |
| `GET /v2/me?country_id=` | 200; provisions on first call | 200, or 404 before the first saved record |
| `PATCH /v2/me` | Updates `first_name`, `last_name`, `primary_country` | 403 |
| `GET /v2/me/export` | The user and every association, all countries | The same; `user: null` and empty lists before the first saved record |
| `POST /v2/me/upgrade?country_id=` | Requires the header too (422 without it); `{"item": MeItem, "outcome": ...}` | 401 (a bearer token is required) |
| `DELETE /v2/me` | 204; deletes data, then the Auth0 user when configured | 204; deletes data, never calls Auth0 |
| `/v2/user-policies`, `/v2/user-households`, `/v2/user-simulations`, `/v2/user-reports` | POST (201), list, GET, PATCH, DELETE (204), owner-scoped | The same; reads never provision |
| `GET /v2/shared-reports/{id}?country_id=` | No credential: any user's saved report in that country, without its owner (404 when none) | The same |

### Shared reports

A saved report's ID is its shareable link, so `GET /v2/shared-reports/{id}`
takes no credential and sits outside the authenticated user-report router. It
never provisions a user. Its item is `{id, country_id, legacy_report_id, name,
source_note, provisions, validation, budget_window_years, baseline_reform,
last_run_at, created_at, updated_at}`:

- `user_id`, `user_policy_id`, and `baseline_user_policy_id` are left out;
  the owner and the owner's saved reforms stay private.
- `baseline_reform` is `{"name": ...}` when the report was compared with one
  of the owner's saved reforms, and null otherwise, including after that
  reform is deleted.
- Anyone holding the ID can read the report's name, source note, and
  provisions. There is no shared list or search, and the owner routes stay
  owner-scoped.

`MeItem` is `{id, user_type, primary_country, first_name, last_name, email,
created_at}`; `user_type` is `standard` or `unauthenticated`, and
`primary_country` is null only for an unauthenticated user. The upgrade
response is
`{"status": "ok", "message": null, "result": {"item": <MeItem of the signed-in
user>, "outcome": "converted" | "merged" | "none"}}`.

Status conventions follow the existing v2 routes. Schema, query, and header
validation failures return 422 (`Invalid API v2 request`). Contradictory
references, such as a body and query `country_id` mismatch, return 400.
Unknown v1 references, and a `user_policy_id` that is not the caller's, return
422 with a specific message. Mirror-owned rows return 409. Oversized bodies
return 413.

## Schema (one autogenerated revision)

Revision `fbb7488ebe8a` (`link signed-in users to v1-anchored associations`,
parent `91af4fc8d8c1`) was regenerated, under the same revision ID, with
`uv run alembic -c alembic-v2.ini revision --autogenerate --rev-id fbb7488ebe8a`
from the final SQLModel metadata. It has no post-generation corrections.

- `users`: adds `user_type varchar(16)` NOT NULL with server default
  `'standard'`, so every existing row and every insert by an earlier Public
  API revision is standard. `primary_country` becomes nullable. Adds
  `ck_users_user_type` (`user_type IN ('unauthenticated', 'standard')`) and
  `ck_users_standard_primary_country`
  (`user_type = 'unauthenticated' OR primary_country IS NOT NULL`);
  `ck_users_primary_country` is kept.
- `user_identities` (new): `id`, `user_id` → `users.id` CASCADE, `issuer` and
  `subject` text, `email varchar(320)` nullable, `created_at`, `last_seen_at`;
  `uq_user_identities_issuer_subject`; `ix_user_identities_user_id`.
- `user_policies`: `policy_id` nullable (composite FK kept, `MATCH SIMPLE`);
  adds `legacy_policy_id bigint`, `baseline` (CHECK `current-law` /
  `current-policy`), and `provenance jsonb`. Adds
  `ck_user_policies_policy_ref` and an index on
  `(country_id, legacy_policy_id)`.
- `user_household_associations`: the same pattern with
  `legacy_household_id`.
- `user_simulation_associations` and `user_report_associations` (dormant, so
  reshaped): the foreign keys to v2 `simulations` and `reports` and the old
  `(user_id, simulation_id|report_id)` uniques are dropped. Each gains
  `country_id` (NOT NULL, CHECK), `name`, `description`, a legacy ID, a
  reference CHECK, `UNIQUE(id, country_id)`, and listing indexes. Reports also
  add `user_policy_id` → `user_policies.id` ON DELETE SET NULL (the saved
  reform the report was run from), `baseline_user_policy_id` →
  `user_policies.id` ON DELETE SET NULL (the saved reform it was compared
  with, when not current law; the baseline's name is that reform's name, so no
  label is stored), `source_note`, `provisions jsonb` (each provision may carry
  optional `growth`, `growth_start`, `growth_base`, `growth_round_to` and
  `growth_round` settings), `validation jsonb`, and `budget_window_years smallint`
  (the years of the budget window run with the report, from its year; NULL for
  none, otherwise 2 to 75 by `ck_user_report_associations_budget_window_years`,
  matching the economy route's limit).
- The old `country` and `label` columns on those two tables are retired but
  kept: `country` becomes nullable and nothing reads or writes either column.
  The previous Public API revision still maps them, so dropping them would
  break it during the deploy window or an application rollback (see
  "Rollback").

The models drop the `user_associations` relationships from v2 simulations and
reports. `V2_ALEMBIC_HEAD_REVISION` is `fbb7488ebe8a`.

### Reshape safety

The reshape requires `user_simulation_associations` and
`user_report_associations` to be empty. Adding a NOT NULL `country_id` also
fails naturally when rows exist, following the Stage 11 precedent. The
read-only qualification command reports all four association row counts. It
stops when the revision is pending and a dormant table holds rows:

```bash
V2_MIGRATION_DATABASE_URL=... V2_SUPABASE_PROJECT_REF=... V2_SUPABASE_ENVIRONMENT=... \
  uv run python -m policyengine_api.data.v2.user_association_migration_qualification
```

It uses SQLAlchemy in a Postgres read-only, rolled-back transaction and never
prints the URL. `seed-v2-database.yml` runs it, through
`scripts/qualify_v2_user_association_migration.py`, before every schema
upgrade. Before merging, an operator should run it read-only against staging
and production and confirm both dormant tables are empty.

### Rollback

Roll forward whenever possible. The schema lets the previous Public API
revision run (see "Schema compatibility" below), but that revision serves
`/v2/user-policies` and `/v2/user-households` without authentication: any
caller can list a user's saved items by `user_id`, read, rename or delete one
by record ID, and create rows for any user. Rolling the application back
would therefore hand users' saved work to anyone.

- **Before any user-owned record exists, an application rollback is safe
  without a database downgrade.** Signed-out saving needs no configuration, so
  treat user-owned records as existing from the moment this revision serves
  traffic in an environment.
- **Once any user-owned record exists, signed in or not, an application
  rollback must apply the Stage 12A rollback guard first**
  (`docs/migration/armor/proposed/20261013-pol-api-lb-stage-12a-rollback-guard.yaml`):
  1. Create the Cloud Armor rule that denies `/v2/me*` (including
     `/v2/me/upgrade`) and `/v2/user-*` with 403 at the load balancer.
  2. Set the Cloud Run service's ingress to `internal-and-cloud-load-balancing`,
     because `*.run.app` URLs bypass Cloud Armor.
  3. Shift traffic to the previous revision, and check that
     `https://api.policyengine.org/v2/user-policies?country_id=us` returns 403.
  4. Remove the guard and restore ingress only after a Stage 12A-or-later
     revision serves all traffic again.

  While the guard is in place, saved work is unavailable, signed in or not:
  app v3 shows its account error and saves fail. v1 routes and the `/v2`
  metadata, policy, and household routes are unaffected. Run.app URLs, which
  CI smoke tests use, are closed too. Staging is not behind the load balancer
  and holds only test accounts, so it needs no guard.
- **Nothing else in the previous revision exposes Stage 12A data.** Its native
  routes were checked one by one: only `/v2/user-policies` and
  `/v2/user-households` (all five operations each) read or write user
  association rows. `/v2/me*`, `/v2/user-simulations`, and `/v2/user-reports`
  do not exist there and fall through to its 404 handler. `/v2/policies` and
  `/v2/households` serve shared v2 artifacts that Stage 12A does not change.
  Its Flask v1 routes read and write only Cloud SQL. Its Stage 10 saved-policy
  mirror reads and writes only legacy transition users (standard users found
  through `legacy_user_mappings`); no signed-in or unauthenticated user is
  ever one of them, because Stage 12A never adopts a legacy user.
- **Behind the guard, one more previous-revision gap does not matter.** Its
  `/v2/user-policies` and `/v2/user-households` responses require a non-null
  `policy_id` / `household_id`, so any response that includes a legacy-only
  row (a v1 reference with no v2 copy) fails with 500.
- **A database downgrade is lossy.** It restores NOT NULL on `policy_id`,
  `household_id`, `simulation_id`, `report_id`, `country`, and
  `users.primary_country`, so it fails while legacy-only rows, any simulation
  or report associations, or any unauthenticated user exist. Removing them
  first deletes users' saved work.

### Schema compatibility

The revision is additive (expand-only) for everything the previous Public API
revision maps: it drops no table or column, and it adds no required column
without a server default to any table that revision writes. The only new
required columns are `country_id` on the simulation and report associations,
which that revision maps but never inserts into, and `users.user_type`, whose
server default makes every user the previous revision creates (its Stage 10
transition users, which always have a primary country) standard, so both new
`users` checks pass. Relaxing `users.primary_country` to nullable affects only
unauthenticated users. The previous revision reads `users` only to confirm a
row exists (in its `/v2/user-policies` and `/v2/user-households` creates,
which the rollback guard denies) and through `legacy_user_mappings`; loading a
row with a NULL `primary_country` does not fail there.

The lifecycle test `test_stage_12a_schema_serves_the_previous_revision`
exercises this rather than only comparing columns. It reflects the schema at
the parent revision with SQLAlchemy and upgrades to head. Then, through the
reflected parent tables, it does the following for every table the parent
revision maps:

- inserts a row that supplies only the parent's required columns (plus the
  nullable values that the parent's own check constraints demand);
- reads the row back with every parent column;
- rewrites every non-key column;
- deletes the row.

Rows of the two dormant tables are inserted through head's tables, since only
new code writes them, and are then read, rewritten, and deleted through the
parent's. The test also deletes, through the parent's `users` table, a user who
owns rows in all four association tables and a `user_identities` row, and it
checks that every one of them cascades away. It fails if head drops a parent
column, or adds a required column without a server default to a table the
parent revision writes.

## Settings

No setting is new for signed-out saving: the unauthenticated-user header works
whether or not the Auth0 settings below are present. Without them, bearer
requests keep their 401/503 behavior, and signed-out requests still work.

| Setting | Source | Meaning |
| --- | --- | --- |
| `PUBLIC_API_AUTH_REQUIRED` | GitHub variable (`staging`, `production`) | `1` requires issuer and audience; `0` allows them to be absent, so bearer requests answer 401 or 503 |
| `PUBLIC_API_AUTH_ISSUER` | GitHub variable | Auth0 issuer URL, normalized to a trailing `/` (the custom domain, for example `https://auth.policyengine.org/`) |
| `PUBLIC_API_AUTH_AUDIENCE` | GitHub variable | The Public API resource-server identifier |
| `AUTH0_MANAGEMENT_DOMAIN` | GitHub variable (optional, `production` only) | Canonical tenant domain (the Management API is not served on custom domains) |
| `AUTH0_MANAGEMENT_CLIENT_ID` | GitHub variable (optional, `production` only) | M2M client with `delete:users` |
| `AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE` | GitHub secret (optional, `production` only) | Secret Manager version holding the M2M client secret |

> **Set the final issuer before the first sign-in.** `user_identities` is
> keyed by `(issuer, subject)`, so `PUBLIC_API_AUTH_ISSUER` must hold its
> final value, the custom domain (for example
> `https://auth.policyengine.org/`) rather than the tenant's `*.auth0.com`
> domain, before anyone signs in to that environment. Changing it later
> makes every existing user look new: their next sign-in provisions a new,
> empty account, and their old account and its saved work are orphaned,
> with no sign-in that can read, export, or delete them. Nothing re-keys
> identities automatically.

`readiness.validate_policy_runtime_configuration` validates the
`PUBLIC_API_AUTH_*` and `AUTH0_MANAGEMENT_*` settings. Inconsistent values fail
readiness, which is the deploy gate. Request handling reads the
`PUBLIC_API_AUTH_*` settings only for a bearer token, so nothing in them
blocks a signed-out request. `validate_cloud_run_deploy_env.sh` requires
`PUBLIC_API_AUTH_REQUIRED` (`0` or `1`) and checks the issuer, audience, and
all-or-none Management settings, and it rejects Management settings outside
production. `deploy_cloud_run_candidate.sh` writes them to
the revision. The release test step unsets them.

The staging deploy gate (`tests/integration/test_live_v2_policies.py`) also
needs the following in the GitHub `staging` environment:

| Setting | Kind |
| --- | --- |
| `STAGING_AUTH0_TEST_DOMAIN` | variable; its tokens' `iss` must equal staging `PUBLIC_API_AUTH_ISSUER` |
| `STAGING_AUTH0_TEST_AUDIENCE` | variable; equals staging `PUBLIC_API_AUTH_AUDIENCE` |
| `STAGING_AUTH0_TEST_CLIENT_ID`, `STAGING_AUTH0_TEST_CLIENT_SECRET` | secrets; staging-only CI application with the password grant |
| `STAGING_AUTH0_TEST_USERNAME`, `STAGING_AUTH0_TEST_PASSWORD` | secrets; dedicated test user |
| `STAGING_AUTH0_TEST_REALM` | optional variable; database connection for the password-realm grant |

The live test deletes the test user's PolicyEngine account at the start and the
end of each signed-in check. Its signed-out check saves work as fresh random
browser UUIDs, converts one into the test user's account and merges another
into it, and deletes everything it created, so it can run repeatedly. With
Management API deletion configured, deleting the account would also delete
the CI user from Auth0, so the staging deploy job never receives the
`AUTH0_MANAGEMENT_*` settings and the deploy validation rejects them outside
production.

## Auth0 prerequisites (operator)

Configure staging first, then production:

1. **Custom domain** (for example `auth.policyengine.org`). Tokens then carry
   that issuer. Finish this before setting `PUBLIC_API_AUTH_ISSUER`, which
   must not change once a user has signed in (see "Settings").
2. **Public API resource server** (RS256), whose identifier becomes
   `PUBLIC_API_AUTH_AUDIENCE`.
3. **Social connections and SPA applications** for app v3.
4. **Staging-only CI application** with the password grant, plus a test user.
5. **Optional Management API M2M client** with `delete:users`, production
   only. Store its client secret in Secret Manager, put the version's resource
   name in the `production` GitHub secret
   `AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE`, and grant the Cloud Run runtime
   service account (the `GCP_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT` GitHub secret)
   `roles/secretmanager.secretAccessor` on that secret:

   ```bash
   gcloud secrets add-iam-policy-binding <secret-name> \
     --project=<project> \
     --member="serviceAccount:<runtime-service-account>" \
     --role="roles/secretmanager.secretAccessor"
   ```

   Without the grant, every signed-in account deletion returns 503 and
   deletes nothing.

## Rollout

1. Create the GitHub variables and secrets above. Every deploy now requires
   `PUBLIC_API_AUTH_REQUIRED`. Staging deploys also need the test-user settings,
   because the live test is a deploy gate.
2. Run the qualification command read-only against staging and production.
3. Merge. The release migration applies `fbb7488ebe8a` after the seed
   workflow's qualification step passes.
4. Staging: `PUBLIC_API_AUTH_REQUIRED=1` with the staging issuer and audience.
   The staging candidate must pass the signed-in and signed-out live tests
   before promotion.
5. Production: signed-out saving works as soon as the revision serves
   traffic. Set the production Auth0 values once production Auth0, including
   its custom domain, is ready; the issuer cannot change after the first
   sign-in (see "Settings"). The candidate smoke test checks that `/v2/me` and
   `/v2/user-*` requests without a credential, or with a malformed
   unauthenticated-user header, return 401. After promotion, also check that
   `curl https://api.policyengine.org/v2/user-policies?country_id=us`
   returns 401.
6. Apply the proposed Cloud Armor write throttle in preview
   (`docs/migration/armor/proposed/20261012-pol-api-lb-stage-12a-user-writes.yaml`)
   and enforce it only after the runbook's checks. It is the only bound on how
   fast one client can create unauthenticated users.
7. Keep the rollback guard
   (`docs/migration/armor/proposed/20261013-pol-api-lb-stage-12a-rollback-guard.yaml`)
   ready. From the first user-owned record on, signed in or not, it is a
   precondition for any application rollback to a pre-Stage 12A revision (see
   "Rollback").

User-owned routes must never become less restrictive during a cutover. The
migration-contract guard rejects any `/v2/me` or `/v2/user-` contract that
requires neither `Authorization` nor `PolicyEngine-Unauthenticated-User`, and
the registry records each user-owned request once per credential that can make
it.

## Verification

```bash
uv run --frozen --extra dev mypy
uv run pytest tests/unit/v2 tests/unit/libs tests/unit/test_readiness.py \
  tests/unit/test_query_parameters.py tests/unit/test_cloud_run_deploy_scripts.py \
  tests/unit/test_migration_contract_artifacts.py tests/contract -q
V2_ALEMBIC_DISPOSABLE_TEST=1 \
V2_MIGRATION_DATABASE_URL="postgresql+psycopg://.../policyengine_v2_alembic_test" \
  uv run pytest tests/integration/test_alembic_v2_lifecycle.py \
  tests/integration/test_v2_user_identity_persistence.py -q
python scripts/export_migration_contracts.py
python scripts/run_quality_guards.py
```

The disposable-Postgres suite proves the following:

- concurrent first sign-ins create one user;
- concurrent first writes by one signed-out browser create one
  unauthenticated user, with every other user column NULL;
- concurrent upgrades of one browser convert exactly once;
- two browsers upgrading into a new account at once share it: one converts,
  the other merges;
- a merge moves all four association kinds with their IDs, keeps report links
  valid, and deletes the unauthenticated user;
- a signed-out write waits for a conversion and then gets 401, or, after a
  merge, starts a new unauthenticated user;
- a signed-out account deletion racing a conversion never deletes the
  converted user;
- named `ON CONFLICT` targets work;
- `MATCH SIMPLE` composite keys accept NULL v2 references;
- account deletion cascades after removing legacy mappings;
- NaN and Infinity never reach JSONB;
- the parent revision's table usage works against head (see "Schema
  compatibility");
- the qualification transaction is read-only.

## Deferred

- A later autogenerated revision that drops the retired `country` and `label`
  columns from `user_simulation_associations` and `user_report_associations`,
  once no deployable Public API revision maps them.
- A retention policy for unauthenticated users whose browsers never return.
  Nothing expires them today.
- An explicit claim flow for legacy-app users (`POST /v2/me/legacy-claims`).
- Accepting v2 `simulation_id` / `report_id` once the Simulation Entrypoint owns
  those records.
