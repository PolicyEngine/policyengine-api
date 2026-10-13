# Stage 12A: user login and v1-anchored user associations

Stage 12A lets app v3 users sign in with Auth0 social sign-on and saves their
work server-side. The Public API turns the Auth0 identity into a PolicyEngine
user ID and writes that ID onto every saved policy, household, simulation, and
report. Saved records point at the v1 artifacts the app already creates.
Signed-out behavior is unchanged.

## What changed

- **Inbound authentication.** `/v2/me*` and `/v2/user-*` require
  `Authorization: Bearer <Auth0 access token>` for the Public API audience.
  `libs/user_auth.py` validates RS256 tokens against
  `{issuer}.well-known/jwks.json` and checks `iss` and `aud`. The decoder is
  ported from the Simulation Entrypoint. Responses:
  - no token or an invalid token: 401 with `WWW-Authenticate: Bearer`;
  - a machine-to-machine (`…@clients`) token: 403;
  - authentication not configured, or signing keys unreachable: 503.

  Authentication is a router-level dependency
  (`NativeRouteDependencies.require_user`, fail-closed by default). It runs
  before query, path, and body validation. Only a body that is not parseable
  JSON is rejected (422) by FastAPI first.
- **Identity and provisioning.** The new `user_identities` table maps
  `(issuer, subject)` to `users.id`. The first authenticated request inserts the
  user (with `primary_country` from `country_id`) and the identity. A concurrent
  first request loses `UNIQUE(issuer, subject)`, rolls back its savepoint, and
  re-reads, so exactly one user is created. `last_seen_at` is written at most
  hourly. Email is stored only when `email_verified` is true; it is never unique
  and never used for linking. No legacy user is adopted implicitly. Logs carry
  only the v2 user UUID.
- **Ownership.** Request bodies and queries no longer accept `user_id`; the
  owner always comes from the token. Another user's record returns 404.
- **v1 references.** Each association accepts a `legacy_*_id` (a country-scoped
  v1 database ID). A batched, read-only SQLAlchemy connector checks it against
  the v1 mapped models in a short transaction, closed before the v2 transaction
  opens. A missing reference returns 422.
  - `user-policies` and `user-households` also accept the v2 `policy_id` or
    `household_id`. With only a legacy ID, the v2 reference is filled from
    `legacy_policy_mappings` / `legacy_household_mappings` when a mapping
    exists.
  - Changing the legacy ID re-resolves the v2 reference, or clears it.
  - `user-simulations` and `user-reports` accept only legacy IDs in 12A.
- **Stage 10 mirror rows.** A `user_policies` row with a
  `legacy_user_policy_mappings` entry returns 409 on PATCH and DELETE. The
  mirror projection now also records `legacy_policy_id`.
- **Imports.** `POST /v2/me/imports` takes up to 500 browser-local items in a
  1 MiB body. It is idempotent on `UNIQUE(user_id, client_ref)`: an existing
  `client_ref` in the import country returns its stored ID unchanged. Items
  with an unknown v1 reference or an invalid shape are skipped and reported;
  so is a `client_ref` the user already holds in another country
  (`client_ref_conflict`), which is never linked across countries. A report's
  `user_policy_client_ref` resolves only against the user's policies in the
  import country.
- **Request bounds.** Every `/v2/me*` and `/v2/user-*` write rejects a body
  over 256 KiB with 413 (imports allow 1 MiB). FastAPI reads and parses the
  whole JSON body before any dependency runs, so this check does not limit
  what is read or parsed; Cloud Run's 32 MiB request limit does. The check is
  a dependency that runs after authentication, so an oversized body gets 413
  before any body-validation error is reported and before any service or
  database work, which bounds what can be stored. Caller
  fields are also bounded on single writes and imports alike: `description`
  and `source_note` at 10,000 characters, report `provisions` at 64 KiB
  serialized, and the report `validation` snapshot at 500 calibration matches
  and 200 scorecard programs, with bounded strings (64 to 1,024 characters).
  `provenance` was already bounded (enumerated fields and a 2,048-character
  `ref`). Every user-route float and JSON value also rejects NaN and Infinity:
  Python's JSON parser accepts them but Postgres JSONB cannot store them. A
  single write containing one returns 422; an import item containing one is
  skipped as `invalid`.
- **Account deletion.** When the Management API is configured, `DELETE
  /v2/me` first reads the client secret from Secret Manager and obtains a
  Management token. If either fails, it returns 503 with nothing deleted. It
  then deletes the user's `legacy_user_mappings` rows (RESTRICT FK), then the
  user (identities and associations cascade), then the Auth0 user. A 401 from
  Auth0 drops the cached token and retries once with a fresh one. If the Auth0
  call still fails after the data is gone, the route returns 502 and a retry
  is safe. The Management settings are read only for this route.

The wire contract (fields, statuses, nested report types) is the Stage 12A HTTP
contract shared with `policyengine-app-v2`. The generated route inventory is in
`docs/engineering/migration-contracts.md`.

| Route | Behavior |
| --- | --- |
| `GET /v2/me?country_id=` | Returns the user; provisions on first call |
| `PATCH /v2/me` | Updates `first_name`, `last_name`, `primary_country` |
| `GET /v2/me/export` | Returns the user and every association, all countries |
| `POST /v2/me/imports` | Idempotent bulk import; returns `id_map` and `skipped` |
| `DELETE /v2/me` | 204; deletes data, then the Auth0 user when configured |
| `/v2/user-policies`, `/v2/user-households`, `/v2/user-simulations`, `/v2/user-reports` | POST (201), list, GET, PATCH, DELETE (204), owner-scoped |

Status conventions follow the existing v2 routes. Schema and query validation
failures return 422 (`Invalid API v2 request`). Contradictory references, such
as a body and query `country_id` mismatch, return 400. Unknown v1 references,
and a `user_policy_id` that is not the caller's, return 422 with a specific
message. Single-create `client_ref` clashes and mirror-owned rows return 409.
Oversized bodies return 413.

## Schema (one autogenerated revision)

Revision `fbb7488ebe8a` (`link signed-in users to v1-anchored associations`,
parent `91af4fc8d8c1`) was produced with
`uv run alembic -c alembic-v2.ini revision --autogenerate` from the final
SQLModel metadata. It has no post-generation corrections.

- `user_identities` (new): `id`, `user_id` → `users.id` CASCADE, `issuer` and
  `subject` text, `email varchar(320)` nullable, `created_at`, `last_seen_at`;
  `uq_user_identities_issuer_subject`; `ix_user_identities_user_id`.
- `user_policies`: `policy_id` nullable (composite FK kept, `MATCH SIMPLE`);
  adds `legacy_policy_id bigint`, `baseline` (CHECK `current-law` /
  `current-policy`), `provenance jsonb`, and `client_ref varchar(64)`. Adds
  `ck_user_policies_policy_ref`, `uq_user_policies_user_client_ref`, and an
  index on `(country_id, legacy_policy_id)`.
- `user_household_associations`: the same pattern with
  `legacy_household_id`.
- `user_simulation_associations` and `user_report_associations` (dormant, so
  reshaped): the foreign keys to v2 `simulations` and `reports` and the old
  `(user_id, simulation_id|report_id)` uniques are dropped. Each gains
  `country_id` (NOT NULL, CHECK), `name`, `description`, a legacy ID,
  `client_ref`, a reference CHECK, `UNIQUE(id, country_id)`,
  `UNIQUE(user_id, client_ref)`, and listing indexes. Reports also add
  `user_policy_id` → `user_policies.id` ON DELETE SET NULL, `source_note`,
  `provisions jsonb`, and `validation jsonb`.
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
would therefore hand signed-in users' saved work to anyone.

- **Before any signed-in user exists, an application rollback is safe without
  a database downgrade.** Treat signed-in users as existing from the moment an
  environment has `PUBLIC_API_AUTH_ISSUER` configured, because from then on
  anyone with an Auth0 account can provision one.
- **Once any signed-in user exists, an application rollback must apply the
  Stage 12A rollback guard first**
  (`docs/migration/armor/proposed/20261013-pol-api-lb-stage-12a-rollback-guard.yaml`):
  1. Create the Cloud Armor rule that denies `/v2/me*` and `/v2/user-*` with
     403 at the load balancer.
  2. Set the Cloud Run service's ingress to `internal-and-cloud-load-balancing`,
     because `*.run.app` URLs bypass Cloud Armor.
  3. Shift traffic to the previous revision, and check that
     `https://api.policyengine.org/v2/user-policies?country_id=us` returns 403.
  4. Remove the guard and restore ingress only after a Stage 12A-or-later
     revision serves all traffic again.

  While the guard is in place, saved work is unavailable: app v3 shows its
  account error and signed-in saves fail. Signed-out flows, v1 routes, and the
  `/v2` metadata, policy, and household routes are unaffected. Run.app URLs,
  which CI smoke tests use, are closed too. Staging is not behind the load
  balancer and holds only test accounts, so it needs no guard.
- **Nothing else in the previous revision exposes Stage 12A data.** Its native
  routes were checked one by one: only `/v2/user-policies` and
  `/v2/user-households` (all five operations each) read or write user
  association rows. `/v2/me*`, `/v2/user-simulations`, and `/v2/user-reports`
  do not exist there and fall through to its 404 handler. `/v2/policies` and
  `/v2/households` serve shared v2 artifacts that Stage 12A does not change.
  Its Flask v1 routes read and write only Cloud SQL. Its Stage 10 saved-policy
  mirror writes only legacy transition users, and no signed-in user is ever
  one of them, because Stage 12A never adopts a legacy user.
- **Behind the guard, one more previous-revision gap does not matter.** Its
  `/v2/user-policies` and `/v2/user-households` responses require a non-null
  `policy_id` / `household_id`, so any response that includes a legacy-only
  row (a v1 reference with no v2 copy) fails with 500.
- **A database downgrade is lossy.** It restores NOT NULL on `policy_id`,
  `household_id`, `simulation_id`, `report_id`, and `country`, so it fails
  while legacy-only rows or any simulation or report associations exist.
  Removing them first deletes users' saved work.

### Schema compatibility

The revision is additive for everything the previous Public API revision maps:
it drops no table or column, and it adds no required column without a server
default to any table that revision writes. The only new required columns are
`country_id` on the simulation and report associations, which that revision
maps but never inserts into.

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

| Setting | Source | Meaning |
| --- | --- | --- |
| `PUBLIC_API_AUTH_REQUIRED` | GitHub variable (`staging`, `production`) | `1` requires issuer and audience; `0` allows them to be absent, so user routes answer 401 or 503 |
| `PUBLIC_API_AUTH_ISSUER` | GitHub variable | Auth0 issuer URL, normalized to a trailing `/` (the custom domain, for example `https://auth.policyengine.org/`) |
| `PUBLIC_API_AUTH_AUDIENCE` | GitHub variable | The Public API resource-server identifier |
| `AUTH0_MANAGEMENT_DOMAIN` | GitHub variable (optional, `production` only) | Canonical tenant domain (the Management API is not served on custom domains) |
| `AUTH0_MANAGEMENT_CLIENT_ID` | GitHub variable (optional, `production` only) | M2M client with `delete:users` |
| `AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE` | GitHub secret (optional, `production` only) | Secret Manager version holding the M2M client secret |

`readiness.validate_policy_runtime_configuration` validates the
`PUBLIC_API_AUTH_*` and `AUTH0_MANAGEMENT_*` settings. Inconsistent values fail
readiness, which is the deploy gate. `validate_cloud_run_deploy_env.sh` requires
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
end. With Management API deletion configured, that would also delete the CI
user from Auth0, so the staging deploy job never receives the
`AUTH0_MANAGEMENT_*` settings and the deploy validation rejects them outside
production.

## Auth0 prerequisites (operator)

Configure staging first, then production:

1. **Custom domain** (for example `auth.policyengine.org`). Tokens then carry
   that issuer.
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

   Without the grant, every account deletion returns 503 and deletes nothing.

## Rollout

1. Create the GitHub variables and secrets above. Every deploy now requires
   `PUBLIC_API_AUTH_REQUIRED`. Staging deploys also need the test-user settings,
   because the live test is a deploy gate.
2. Run the qualification command read-only against staging and production.
3. Merge. The release migration applies `fbb7488ebe8a` after the seed
   workflow's qualification step passes.
4. Staging: `PUBLIC_API_AUTH_REQUIRED=1` with the staging issuer and audience.
   The staging candidate must pass the signed-in live test before promotion.
5. Production: set the production values once production Auth0 is ready. The
   candidate smoke test checks that anonymous `/v2/me` and `/v2/user-*`
   requests return 401. After promotion, also check that
   `curl https://api.policyengine.org/v2/user-policies?country_id=us` returns
   401.
6. Apply the proposed Cloud Armor throttles in preview
   (`docs/migration/armor/proposed/20261012-pol-api-lb-stage-12a-user-writes.yaml`)
   and enforce them only after the runbook's checks.
7. Keep the rollback guard
   (`docs/migration/armor/proposed/20261013-pol-api-lb-stage-12a-rollback-guard.yaml`)
   ready. From the first signed-in user on, it is a precondition for any
   application rollback to a pre-Stage 12A revision (see "Rollback").

User-owned routes must never become less restrictive during a cutover. The
migration-contract guard rejects any `/v2/me` or `/v2/user-` contract that does
not require `Authorization`.

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
- concurrent imports are idempotent;
- imports never reuse or link a `client_ref` from another country;
- named `ON CONFLICT` targets work;
- `MATCH SIMPLE` composite keys accept NULL v2 references;
- account deletion cascades after removing legacy mappings;
- NaN and Infinity never reach JSONB, and an import skips the item holding one;
- the parent revision's table usage works against head (see "Schema
  compatibility");
- the qualification transaction is read-only.

## Deferred

- A later autogenerated revision that drops the retired `country` and `label`
  columns from `user_simulation_associations` and `user_report_associations`,
  once no deployable Public API revision maps them.
- An explicit claim flow for legacy-app users (`POST /v2/me/legacy-claims`).
- Accepting v2 `simulation_id` / `report_id` once the Simulation Entrypoint owns
  those records.
