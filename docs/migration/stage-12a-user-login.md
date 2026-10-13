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
  over 256 KiB with 413 (imports allow 1 MiB). The check runs after
  authentication and before body validation or any service work. Caller
  fields are also bounded on single writes and imports alike: `description`
  and `source_note` at 10,000 characters, report `provisions` at 64 KiB
  serialized, and the report `validation` snapshot at 500 calibration matches
  and 200 scorecard programs, with bounded strings (64 to 1,024 characters).
  `provenance` was already bounded (enumerated fields and a 2,048-character
  `ref`).
- **Account deletion.** `DELETE /v2/me` deletes the user's
  `legacy_user_mappings` rows (RESTRICT FK), then the user (identities and
  associations cascade), then the Auth0 user through the Management API when
  configured. If the Auth0 call fails after the data is gone, the route returns
  502 and a retry is safe.

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

The revision is additive for everything the previous Public API revision maps:
it drops no table or column and makes no nullable column required. The
lifecycle test `test_stage_12a_revision_keeps_the_previous_revision_loadable`
enforces this.

- **Rolling back the application is safe without a database downgrade.** The
  previous revision serves its routes against this schema, and deleting a user
  through its models still cascades through the simulation and report
  associations.
- **One exception.** The previous revision's unauthenticated
  `/v2/user-policies` and `/v2/user-households` responses require a non-null
  `policy_id` / `household_id`. Once a signed-in user owns a legacy-only row (a
  v1 reference with no v2 copy), any of those responses that includes the row
  fails with 500 under the previous revision. Nothing else is affected, and the
  current production app does not call those routes.
- **A database downgrade is lossy.** It restores NOT NULL on `policy_id`,
  `household_id`, `simulation_id`, `report_id`, and `country`, so it fails
  while legacy-only rows or any simulation or report associations exist.
  Removing them first deletes users' saved work. Prefer an application
  rollback.

## Settings

| Setting | Source | Meaning |
| --- | --- | --- |
| `PUBLIC_API_AUTH_REQUIRED` | GitHub variable (`staging`, `production`) | `1` requires issuer and audience; `0` allows them to be absent, so user routes answer 401 or 503 |
| `PUBLIC_API_AUTH_ISSUER` | GitHub variable | Auth0 issuer URL, normalized to a trailing `/` (the custom domain, for example `https://auth.policyengine.org/`) |
| `PUBLIC_API_AUTH_AUDIENCE` | GitHub variable | The Public API resource-server identifier |
| `AUTH0_MANAGEMENT_DOMAIN` | GitHub variable (optional) | Canonical tenant domain (the Management API is not served on custom domains) |
| `AUTH0_MANAGEMENT_CLIENT_ID` | GitHub variable (optional) | M2M client with `delete:users` |
| `AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE` | GitHub secret (optional) | Secret Manager version holding the M2M client secret |

`readiness.validate_policy_runtime_configuration` validates the
`PUBLIC_API_AUTH_*` and `AUTH0_MANAGEMENT_*` settings. Inconsistent values fail
readiness, which is the deploy gate. `validate_cloud_run_deploy_env.sh` requires
`PUBLIC_API_AUTH_REQUIRED` (`0` or `1`) and checks the issuer, audience, and
all-or-none Management settings. `deploy_cloud_run_candidate.sh` writes them to
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
end. Leave the `AUTH0_MANAGEMENT_*` settings unset in staging, or the CI user
would also be removed from Auth0.

## Auth0 prerequisites (operator)

Configure staging first, then production:

1. **Custom domain** (for example `auth.policyengine.org`). Tokens then carry
   that issuer.
2. **Public API resource server** (RS256), whose identifier becomes
   `PUBLIC_API_AUTH_AUDIENCE`.
3. **Social connections and SPA applications** for app v3.
4. **Staging-only CI application** with the password grant, plus a test user.
5. **Optional Management API M2M client** with `delete:users`.

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
- the qualification transaction is read-only.

## Deferred

- A later autogenerated revision that drops the retired `country` and `label`
  columns from `user_simulation_associations` and `user_report_associations`,
  once no deployable Public API revision maps them.
- An explicit claim flow for legacy-app users (`POST /v2/me/legacy-claims`).
- Accepting v2 `simulation_id` / `report_id` once the Simulation Entrypoint owns
  those records.
