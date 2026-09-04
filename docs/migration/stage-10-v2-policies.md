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
database read/write settings. It then performs the complete activation,
controlled-failure, retry, and application-rollback exercise described below.
Production schema jobs are not eligible to run until that job has restored and
verified the exact Cloud SQL-only staging revision.

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

The automated exercise deploys this selection as a distinct no-traffic
revision, verifies the exact immutable image and environment configuration,
and then assigns staging traffic to that revision. It also deploys a separate
no-traffic revision whose staging-only Secret Manager resource contains an
intentionally invalid password for the same staging Supabase project. That
revision uses `/health-check` only for process startup so the test can send a
real v1 write and verify the HTTP 503 response produced by an unavailable v2
database. The invalid secret is accessible only to the staging runtime service
account and does not identify a production resource.

Under this selection, a core-policy mutation commits Cloud SQL first and then
completes its policy transaction in Supabase. A saved-policy mutation commits
its source row, incremented revision, and complete event in one Cloud SQL
transaction. The same request then processes that source's pending events in
revision order and records `processed_at` only after the corresponding
Supabase transaction commits.

Canada, Nigeria, and Israel remain supported by v1 but have no v2 catalog in
this phase. Their policy and saved-policy mutations continue using Cloud SQL
only under `DB_WRITE_POLICY=dual_write`: they create no v2 snapshot or mirror
event and do not access Supabase.

A Supabase failure returns HTTP 503. An identical client retry reads the
already committed v1 row, appends the next revision when applicable, and first
replays any retained earlier event. Destination revision and fingerprint
checks make a replay safe if Supabase committed but the Cloud SQL processing
marker did not. There is no background processor or reconciliation process.

The v2 runtime applies one five-second value to pool acquisition, PostgreSQL
connection establishment, and each SQL statement. The API does not retry these
operations internally. Native v2 routes and v1 mirroring return a secret-safe
HTTP 503 for a timeout or other SQLAlchemy database failure so the caller can
retry the complete request.

Browser preflight requests are handled by the outer ASGI CORS middleware before
FastAPI or Flask route resolution. It permits the public HTTP methods and
request headers used by v1 and v2, exposes `X-PolicyEngine-Request-Id`, and
applies CORS headers to typed errors and service-unavailable responses. Route
functions do not implement separate preflight behavior.

## Monitoring

Monitor structured events with metric names `v1_policy_mirror_operations` and
`v1_user_policy_mirror_operations`. Alert on `outcome=error`, grouped by
`failure_category` and country. Events include the legacy integer ID,
destination UUID when committed, attempted and completed database sources, and
duration. They do not include policy JSON, presentation data, database URLs, or
credentials.

Verify during staged activation that:

- native policy and association create/read/list/update/delete operations use
  the initialized catalog and Supabase only;
- both newly created and existing v1 policies receive durable mappings;
- v1 saved-policy label updates change association `name`, while v1-only field
  updates change only the mapping fingerprint;
- saved-policy event revisions are processed in ascending order, successful
  events have `processed_at`, and failed events retain a null `processed_at`;
- all v1 reads continue to query Cloud SQL and all v1 responses retain integer
  IDs without v2 UUIDs.

## Application Rollback

Set `DB_WRITE_POLICY=cloud_sql` or route traffic to the prior application
revision. This immediately removes the Supabase requirement from v1 mutations.
Keep `DB_READ_POLICY=cloud_sql`. Do not delete policies, associations, or
mappings already committed in Supabase; they remain valid for later retries.

Application rollback does not automatically downgrade either additive source
schema or the v2 schema. If a schema downgrade is separately approved, first
disable native policy traffic and mirroring, verify that no pending Cloud SQL
events or retained v2 data depend on the revisions, and run the reviewed
Alembic downgrades against their confirmed database targets.

The release workflow restores the exact preceding staging revision with
`DB_WRITE_POLICY=cloud_sql`, verifies the stable service URL, creates another
synthetic v1 policy, confirms that no v2 mapping was created for it, and reads a
policy that was committed to Supabase during activation. It uploads a
90-day-retained JSON artifact containing revision names, timestamps, selector
values, HTTP status summaries, synthetic record identifiers, and non-secret row
counts. The artifact never contains passwords or database URLs.
