# Stage 11 V2 Household Deployment

This runbook applies the reviewed household schemas, makes the native v2
household and user-household resources available, and optionally requires an
immediate copy of each new US or UK v1 household. V1 reads and calculations
continue to use Cloud SQL and integer household identifiers.

## Preconditions

1. Retain the completed Stage 10 evidence that staging uses independently
   writable copies of Cloud SQL and Supabase and that the Stage 10 application
   rollback succeeded. Do not start a Stage 11 staging or production database
   operation until that evidence has been reviewed.
2. Confirm that the selected staging and production GitHub environments name
   different Cloud SQL instances, Supabase project references, v1 credential
   resources, and v2 credential resources. The repository validation scripts
   stop before connecting when a required identity is absent, a staging value
   equals its production counterpart, or a production value differs from its
   declared production identity.
3. Inspect production request telemetry for `PUT /<country_id>/household/<id>`
   over an agreed observation window. Record the query, dates, request count,
   and identified consumers. Stop activation if unexplained use remains,
   because Stage 11 removes that operation.
4. Qualify the exact Supabase target before its Stage 11 revision is applied:

   ```bash
   V2_MIGRATION_DATABASE_URL="postgresql+psycopg://..." \
   V2_SUPABASE_PROJECT_REF="reviewed-project-reference" \
   V2_SUPABASE_ENVIRONMENT="staging" \
   python scripts/qualify_v2_household_migration.py
   ```

   Continue only when the command reports zero `households`,
   `user_household_associations`, simulation household references, report
   household references, and `household_jobs`. A nonzero result requires a
   reviewed preservation decision. The command uses a read-only transaction
   and skips the row check after revision `724b1b11a33e` has been applied.

### Recorded v1 household PUT observation

On 2026-09-08, the production Cloud Run application-request logs were queried
for the closed 30-day interval from `2026-08-09T14:20:00Z` through
`2026-09-08T14:20:00Z` with this filter:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="policyengine-api"
jsonPayload.message="API request served"
jsonPayload.method="PUT"
jsonPayload.path=~"^/(us|uk|ca|ng|il)/household/[0-9]+($|[?])"
```

The query returned 14 successful requests across five household IDs. All 14
had `https://legacy.policyengine.org/` as the referrer: eight used ordinary
Chrome user agents and six identified as YouBot. The latest request occurred
on `2026-08-28T00:04:11Z`. A separate application-repository search found no
app-v2 call site for this PUT operation. The accepted contract decision is to
remove PUT because app-v2 does not use it; production deployment remains a
separate, explicit operation after staging qualification.

## Apply Schemas Before Activation

Apply the generated v1 event-table revision and the generated v2 household
revision before deploying an application revision that can copy v1 creates:

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

Run `current --check-heads` and `check` against both exact targets. The Stage
11 revisions are `7811e0c49301` for MySQL and `724b1b11a33e` for PostgreSQL.
The release workflows apply the v1 and v2 migrations before constructing the
Cloud Run candidate.

## Deployment Configuration

Define these values in both the `staging` and `production` GitHub environments:

```text
ROUTE_IMPL_HOUSEHOLD=flask_fallback
DB_READ_HOUSEHOLD=cloud_sql
DB_WRITE_HOUSEHOLD=cloud_sql
```

`ROUTE_IMPL_HOUSEHOLD` remains `flask_fallback` because the route group still
contains v1 calculation paths assigned to a later migration stage.
`DB_READ_HOUSEHOLD` remains `cloud_sql`. Native `/v2/households` and
`/v2/user-households` requests are registered independently and always use the
server-side Supabase connection; they do not consult these v1 selectors. The
readiness check therefore requires valid v2 runtime database settings even when
`DB_WRITE_HOUSEHOLD=cloud_sql`. The deployment validation rejects
`ROUTE_IMPL_HOUSEHOLD=fastapi_native` because this selector does not yet control
the remaining v1 household and calculation routes.

The deployment script validates all three values and writes them to the Cloud
Run revision. Candidate resolution then reads the exact immutable revision and
compares each value before tests or promotion. Begin staging with
`DB_WRITE_HOUSEHOLD=cloud_sql`. After the native household and association
lifecycles pass, deploy a separate candidate with:

```text
DB_WRITE_HOUSEHOLD=dual_write
```

This selection copies US and UK v1 creates only. Canada, Nigeria, and Israel
remain Cloud SQL-only and open no Supabase connection for v1 household create.

## Immediate Copy and Failure Behavior

For a selected v1 create, one Cloud SQL transaction writes both the household
row and its complete `household_mirror_events` record. After that commit, the
request synchronously translates the retained event and writes the immutable
v2 household plus its legacy mapping in one Supabase transaction. The source
event receives `processed_at` only after the Supabase transaction commits.

If translation or Supabase persistence fails, the v1 source row and event
remain committed, the event remains pending, and the response is HTTP 503. A
repeated POST creates another v1 household row and does not process the first
row's pending event. No background process scans events. Use the exact-event
workflow described below for recovery.

Monitor structured records with `metric_name=v1_household_mirror_operations`.
Alert on `outcome=error`, grouped by `failure_category` and `country_id`, and
inspect `pending_event`. Records contain the legacy identifier, destination
UUID when available, configured and actual database sources, duration, and
outcome; they contain no household values, SQL, database URLs, or credentials.

## Exact-Event Operator

The only supported deployed recovery path is the manually dispatched
`process-v1-household-mirror-event.yml` workflow. It accepts one environment,
one country, and one legacy household ID and refuses an event that is already
marked complete. It never scans a collection.

For each `staging` and `production` GitHub environment:

- protect the environment with the repository's required reviewers;
- set `GCP_DB_MIGRATION_SERVICE_ACCOUNT` to the service account used by the
  workflow's workload-identity authentication;
- set `HOUSEHOLD_MIRROR_OPERATOR_IDENTITY` to that same reviewed service
  account email;
- grant that service account access only to the environment-specific Cloud SQL
  migration password, Cloud SQL instance, and Supabase row-write credential;
- ensure the staging values remain distinct from every production value.

The workflow authenticates as `GCP_DB_MIGRATION_SERVICE_ACCOUNT` and passes
that value as the executing identity. The command compares it with the
separately configured `HOUSEHOLD_MIRROR_OPERATOR_IDENTITY`, validates both
database identities, and records a secret-safe audit result. Run it from the
GitHub Actions interface or with:

```bash
gh workflow run process-v1-household-mirror-event.yml \
  -f deployment_environment=staging \
  -f country_id=us \
  -f legacy_household_id=12345
```

The workflow starts an environment-specific Cloud SQL Auth Proxy and the
command connects through it as `policyengine_schema_migrator`. The
corresponding local command is intended only for an already authenticated
operator with the same explicit settings and an active staging-only proxy:

```bash
bash .github/scripts/run_household_mirror_event_operator.sh \
  --environment staging \
  --country-id us \
  --legacy-household-id 12345
```

## One-Time Staging Evidence and Application Rollback

Stage 11 received the one-time staging qualification recorded below. The
release workflow does not repeat the stateful Stage 11 household exercise on
every deployment: it no longer creates persistent household fixtures, deploys
a controlled-failure database revision, processes a retained event, or changes
staging traffic specifically for Stage 11. This removes recurring end-to-end
coverage and avoids an accumulating dependency on synthetic staging data.

The ordinary staging candidate tests, Stage 10 staging exercise, focused
household tests, disposable cross-database tests, and manually dispatched exact
event operation remain. Production jobs depend on successful completion of the
Stage 10 staging exercise rather than a separate Stage 11 exercise.

### Recorded staging qualification on 2026-09-08

The staging exercise used application commit `93c9b87e` and image digest
`sha256:302c44ca98a956c4b8fb3a4a4f195646b176088f4306aa7a8d0575e8705cfc1a`.
The isolated v1 schema workflow completed in
[run 34242577535](https://github.com/PolicyEngine/policyengine-api/actions/runs/34242577535).
The isolated v2 schema and retained-data qualification completed in
[run 34243258397](https://github.com/PolicyEngine/policyengine-api/actions/runs/34243258397).

The exact Cloud Run revisions were:

- Cloud-SQL-only: `policyengine-api-staging-00087-zim`;
- household dual-write: `policyengine-api-staging-00092-coy`;
- controlled v2 failure: `policyengine-api-staging-00093-law`.

The activation probe passed native create, detail, list, sequential
deduplication, simultaneous equivalent-content creation with statuses 200 and
201 resolving to one UUID, association create/list/reassignment/delete, US and
UK v1 copying, a retained HTTP 503 failure, a distinct-row client retry, v1
PUT rejection, unchanged v1 calculation, and Cloud-SQL-only writes for Canada,
Nigeria, and Israel. Exact-event processing marked the retained source event
complete and associated it with the expected existing v2 household. The two
additional synthetic pending events created by cold-start timeouts were each
processed by explicit legacy ID; the final staging pending-event count was
zero.

GitHub could not manually dispatch the new exact-event workflow before that
workflow exists on the default branch. The qualification therefore ran the
same reviewed operator script locally through the staging-only Cloud SQL proxy
and `policyengine_schema_migrator` database account. The workflow itself is
configured to authenticate with the reviewed migration service account after
merge.

Rollback restored 100% of staging traffic to
`policyengine-api-staging-00087-zim`. A subsequent v1 create returned HTTP 201,
created no mirror event or v2 mapping, and returned HTTP 405 for PUT; the
previously copied and processed v2 mapping remained present. No production
schema, data, service, traffic, or configuration was changed during this
qualification.

Then restore the exact previous Cloud SQL-only application revision or set:

```text
DB_WRITE_HOUSEHOLD=cloud_sql
```

Confirm that a new v1 household create succeeds without Supabase and creates no
mirror event. Leave `DB_READ_HOUSEHOLD=cloud_sql` and
`ROUTE_IMPL_HOUSEHOLD=flask_fallback`. Do not delete previously committed v2
households, mappings, associations, or source events. Application rollback
does not automatically downgrade either schema; any schema downgrade requires
a separate approval and proof that retained data no longer depends on it.

The recorded staging qualification supported the initial Stage 11 review.
Apply the reviewed schema revisions and application image only to independently
verified production targets. Enable native v2 use and v1 create copying as
separate operational decisions and retain the preceding application revision
for immediate rollback.
