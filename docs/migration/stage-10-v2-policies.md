# Stage 10 V2 Policy Deployment

This runbook applies the reviewed v2 policy schema, activates native v2 policy
resources, and optionally requires immediate v1-to-v2 mirroring. V1 reads and
integer identifiers remain in Cloud SQL throughout this stage.

## Preconditions

1. Stage 9 metadata catalogs must be initialized for the v2-supported US and UK
   and the running PolicyEngine.py version. Policy creation does not fall back
   to v1 metadata or another catalog version.
2. The runtime Supabase URL and target identity settings must identify the same
   reviewed project and require TLS. Use either the direct endpoint or
   Supavisor session mode on port 5432. The runtime rejects transaction-pooling
   endpoints on port 6543 because they cannot apply the per-session statement
   timeout.
3. Before applying the Phase 10 revisions beginning with `711ec2f0a5a5`, run the dormant-table qualification
   against the exact migration target:

   ```bash
   V2_MIGRATION_DATABASE_URL="postgresql+psycopg://..." \
   V2_SUPABASE_PROJECT_REF="reviewed-project-reference" \
   V2_SUPABASE_ENVIRONMENT="staging" \
   python scripts/qualify_v2_policy_migration.py
   ```

   Continue only when the result reports zero policies, policy-owned parameter
   values, and user-policy associations requiring preservation. A nonzero count
   requires a separate preservation decision.
4. Staging must use independently writable copies of both production databases.
   The staging Supabase project reference, Cloud SQL instance connection name,
   v1 password secret, and v2 runtime URL secret must all differ from their
   production values. The staging Cloud Run runtime identity must not have
   access to either production database secret.

The repository-level `PRODUCTION_*` variables record non-secret production
identities for comparison. The `staging`, `staging-database`, `production`, and
`production-database` GitHub environments supply their own target identities
and credential-resource names. The deployment and migration scripts stop
before connecting when the selected environment is missing or a staging value
equals its production counterpart.

## Schemas Before Traffic

Apply both generated revisions before deploying code that can enable immediate
v1 saved-policy mirroring. The MySQL revision adds the source revision and
ordered event records; the PostgreSQL revision adds the destination's last
applied source revision.

```bash
ALEMBIC_DATABASE_URL="mysql+pymysql://..." \
uv run alembic -c alembic-v1.ini upgrade head
```

```bash
V2_MIGRATION_DATABASE_URL="postgresql+psycopg://..." \
V2_SUPABASE_PROJECT_REF="reviewed-project-reference" \
V2_SUPABASE_ENVIRONMENT="staging" \
uv run alembic -c alembic-v2.ini upgrade head
```

Run each Alembic `check` command against the same corresponding target and
confirm no metadata/schema difference. The relevant generated revisions are
`3d6e8f553ca5` for MySQL and `af34023a728f` for the current PostgreSQL head.

The release workflow applies and verifies both staging schemas before building
the staging candidate. It replaces, rather than appends to, the candidate's
Cloud SQL attachment and verifies the deployed revision's Cloud SQL attachment,
database identity environment variables, route implementation settings, and
database read/write settings. It runs the normal deployed integration checks and
promotes the exact tested staging revision before production schema jobs become
eligible. A separate Python integration job tests policy and saved-policy
mirroring against disposable MySQL and PostgreSQL databases.

## Activation

The GitHub `staging` and `production` environments must define all three Phase
10 deployment variables:

```text
ROUTE_IMPL_POLICY=flask_fallback
DB_READ_POLICY=cloud_sql
DB_WRITE_POLICY=cloud_sql
```

The deployment workflow passes these values to Cloud Run, rejects missing or
invalid values before deployment, and verifies the exact values on the tagged
candidate revision before testing or promotion. These initial values do not
activate native policy readiness or v1 mirroring.

Native `/v2/policies` and `/v2/user-policies` routes use only the server-side
Supabase connection. The routes are registered as preview resources;
`ROUTE_IMPL_POLICY=fastapi_native` declares them operational for deployment
readiness validation without moving v1 routes away from Flask.

Stage 12A update: `/v2/user-policies` now requires a signed-in user's bearer
token, takes the owner from the token (requests no longer carry `user_id`),
accepts `legacy_policy_id`, and returns 409 for rows maintained by this mirror.
See `docs/migration/stage-12a-user-login.md`.

Native user-policy requests use an existing `users.id` UUID. V1 saved-policy
mirroring keeps the opaque Cloud SQL user identifier out of that foreign-key
column: `legacy_user_mappings` maps the exact v1 string one-to-one to a v2 user
UUID. First use creates a minimal v2 user and mapping in the same Supabase
transaction as the association; later saves and retries reuse that UUID.
`first_name`, `last_name`, and `email` are null for these transition-created
users because the v1 saved-policy record does not supply them. This stage does
not add or infer Auth0 identifiers.

Keep the initial v1 settings explicit:

```text
DB_READ_POLICY=cloud_sql
DB_WRITE_POLICY=cloud_sql
```

After native lifecycle checks pass, require immediate mirroring for US and UK
v1 policy and saved-policy mutations:

```text
DB_READ_POLICY=cloud_sql
DB_WRITE_POLICY=dual_write
```

The release workflow does not repeatedly change the staging write selection or
deploy a revision with deliberately invalid database credentials. Disposable
Python integration tests exercise successful writes, destination transaction
failure, retained-event processing, idempotent retries, and source/destination
rollback using the same MySQL and PostgreSQL engines as the deployed databases.

Under this selection, a core-policy mutation commits Cloud SQL first and then
completes its policy transaction in Supabase. The copy binds the v1 policy to
the running catalog whatever country package version the v1 row was saved
under (its stored `api_version`), the same way the Public API simulates an old
policy with the running country package. A policy is copied when every
parameter path it sets exists in the running catalog and its periods and values
are valid. A saved-policy mutation commits
its source row, incremented revision, and complete event in one Cloud SQL
transaction. The same request then processes that source's pending events in
revision order and records `processed_at` only after the corresponding
Supabase transaction commits.

Canada, Nigeria, and Israel remain supported by v1 but have no v2 catalog in
this phase. Their policy and saved-policy mutations continue using Cloud SQL
only under `DB_WRITE_POLICY=dual_write`: they create no v2 snapshot or mirror
event and do not access Supabase.

A failed copy does not fail the request. Whatever the cause (a Supabase
failure, a policy the v2 catalog cannot translate, or a missing catalog
version), the v1 write is already committed, the copy failure is logged with
its `failure_category`, and the route returns its normal v1 response. A
saved-policy event that failed stays pending, and the next mutation of the same
saved policy replays it, with earlier retained events first. A core policy
whose copy failed is copied again the next time any request writes the same
policy. A core policy that already has a copy returns that copy without being
translated again, so writing it again after a PolicyEngine.py or country
package upgrade does not fail. When two first copies of the same v1 policy run
at once on revisions with different PolicyEngine.py versions, the mapping
committed first is the copy; the other request's v2 policy commits without a
mapping and its record reports `policy_created=false`. Destination revision and fingerprint checks make a replay safe if
Supabase committed but the Cloud SQL processing marker did not. There is no
background processor or reconciliation process.

The v2 runtime applies one five-second value to pool acquisition, PostgreSQL
connection establishment, and each SQL statement. The API does not retry these
operations internally. Native v2 routes return a secret-safe HTTP 503 for a
timeout or other SQLAlchemy database failure so the caller can retry the
complete request. v1 mirroring logs the same failure and returns the v1
response.

Browser preflight requests are handled by the outer ASGI CORS middleware before
FastAPI or Flask route resolution. It permits the public HTTP methods and
request headers used by v1 and v2, exposes `X-PolicyEngine-Request-Id`, and
applies CORS headers to typed errors and service-unavailable responses. Route
functions do not implement separate preflight behavior.

## Missing parameters

A policy can set parameters that a later country package release renamed or
removed. Policy reads report them as `missing_parameters`, so a client can
tell its user and not run the policy:

- `GET /{country}/policy/{policy_id}` checks the v1 policy's parameter paths
  against the leaf parameters of the country model the Public API runs. It
  reads nothing from Supabase, so v1 reads stay on Cloud SQL. The field is
  null for a stored policy that is not a parameter-path object.
- `GET /v2/policies/{policy_id}`, `GET /v2/policies` and `POST /v2/policies`
  check each policy against the catalog of the running PolicyEngine.py
  version. The field is null when that catalog is not published.

Both use the comparison the v2 copy uses (`parameters_missing_from_model`),
and the v2 catalog of a release holds the same leaf parameters as that
release's country model. So a v1 policy reported with missing parameters
is one a first copy under the running release refuses as
`missing_parameters`. A policy copied before a release removed its
parameter keeps that copy, since an existing copy is not translated again;
it is still reported as missing on both routes.

## Monitoring

Monitor structured events with metric names `v1_policy_mirror_operations` and
`v1_user_policy_mirror_operations`. Alert on `outcome=error`, grouped by
`failure_category` and country. Each failed copy also records a fixed
`failure_reason`:

| `failure_category` | `failure_reason` |
| --- | --- |
| `catalog_or_translation` | `missing_parameters` (the policy sets a parameter the running catalog lacks), `invalid_parameter_values`, `empty_parameter_values`, `invalid_period`, `conflicting_values`, `too_many_values` (more than 1,000 dated values), `catalog_absent` (no catalog for the running PolicyEngine.py version), `catalog_query_failed`, `catalog_version_not_found`, `catalog_mismatch` |
| `integrity` | `mapping_conflict`, `content_hash_collision`, `stored_policy_integrity`, `saved_policy_integrity` (any integrity check of a saved-policy copy) |
| `database` | `database_error` |
| `configuration` | `configuration` |
| `unexpected` | `missing_reform_policy` (a saved policy's v1 reform could not be loaded), `unexpected` |
| `missing_mirror_snapshot`, `missing_mirror_revision` | the same value as the category |

Events include the legacy integer ID,
destination UUID when committed, attempted and completed database sources, and
duration. They do not include policy JSON, presentation data, database URLs, or
credentials.

The disposable and route-level tests verify that:

- native policy and association create/read/list/update/delete operations use
  the initialized catalog and Supabase only;
- both newly created and existing v1 policies receive durable mappings,
  including existing policies saved under an older country package version;
- v1 saved-policy label updates change association `name`, while v1-only field
  updates change only the mapping fingerprint;
- saved-policy event revisions are processed in ascending order, successful
  events have `processed_at`, and failed events retain a null `processed_at`;
- all v1 reads continue to query Cloud SQL and all v1 responses retain integer
  IDs without v2 UUIDs.

## Application Rollback

Set `DB_WRITE_POLICY=cloud_sql`, or route traffic to a prior application
revision whose environment selects it, to stop copying. v1 mutations then open
no Supabase connection and record no saved-policy events. A failed copy does
not fail a v1 mutation under `dual_write`, so copy failures on their own are
handled from the `outcome=error` records, not by rolling back. Application
revisions built before that change return HTTP 503 for a failed copy; do not
route traffic to one whose environment selects `DB_WRITE_POLICY=dual_write`.
Keep `DB_READ_POLICY=cloud_sql`. Do not delete policies, associations, or
mappings already committed in Supabase; they remain valid for later retries.

Application rollback does not automatically downgrade either additive source
schema or the v2 schema. If a schema downgrade is separately approved, first
disable native policy traffic and mirroring, verify that no pending Cloud SQL
events or retained v2 data depend on the revisions, and run the reviewed
Alembic downgrades against their confirmed database targets.

The normal staging promotion still restores the previously serving Cloud Run
revision when promotion or the stable-URL health check fails. It does not
create persistent policy fixtures or change the configured write selection as
part of each release.

## Removal of the v1 saved-policy routes

`POST /{country_id}/user-policy`, `GET /{country_id}/user-policy/{user_id}`
and `PUT /{country_id}/user-policy` are removed, along with
`GET /{country_id}/policies`. Only legacy.policyengine.org called them; Cloud
Run request logs for the 30 days to 2026-10-19 showed no saved-policy
requests. No new v1 saved policies are created, so none are copied to v2. The
saved-policy copying and v1 saved-policy service modules stay until dual-write
is deleted, and existing Cloud SQL `user_policies` rows are kept.
