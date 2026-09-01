# Stage 10 V2 Policy Deployment

This runbook applies the reviewed v2 policy schema, activates native v2 policy
resources, and optionally requires immediate v1-to-v2 mirroring. V1 reads and
integer identifiers remain in Cloud SQL throughout this stage.

## Preconditions

1. Stage 9 metadata catalogs must be initialized for every supported country
   and the running PolicyEngine.py version. Policy creation does not fall back
   to v1 metadata or another catalog version.
2. The runtime Supabase URL and target identity settings must identify the same
   reviewed project and require TLS. Use either the direct endpoint or
   Supavisor session mode on port 5432. The runtime rejects transaction-pooling
   endpoints on port 6543 because they cannot apply the per-session statement
   timeout.
3. Before applying revision `711ec2f0a5a5`, run the dormant-table qualification
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
`3d6e8f553ca5` for MySQL and `c21c4a807a49` for PostgreSQL.

## Activation

Native `/v2/policies` and `/v2/user-policies` routes use only the server-side
Supabase connection. The routes are registered as preview resources;
`ROUTE_IMPL_POLICY=fastapi_native` declares them operational for deployment
readiness validation without moving v1 routes away from Flask.

Keep the initial v1 settings explicit:

```text
DB_READ_POLICY=cloud_sql
DB_WRITE_POLICY=cloud_sql
```

After native lifecycle checks pass, require immediate mirroring for v1 policy
and saved-policy mutations:

```text
DB_READ_POLICY=cloud_sql
DB_WRITE_POLICY=dual_write
```

Under this selection, a core-policy mutation commits Cloud SQL first and then
completes its policy transaction in Supabase. A saved-policy mutation commits
its source row, incremented revision, and complete event in one Cloud SQL
transaction. The same request then processes that source's pending events in
revision order and records `processed_at` only after the corresponding
Supabase transaction commits.

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
