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
`DB_READ_HOUSEHOLD` remains `cloud_sql`. (Stage 12A update:
`/v2/user-households` now requires a signed-in user's bearer token, takes the
owner from the token, and accepts `legacy_household_id`; see
`docs/migration/stage-12a-user-login.md`.) Native `/v2/households` and
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
remain committed, the event remains pending, the failure is logged with its
`failure_category`, and the response is the normal HTTP 201 with the v1
household ID. No background process scans events. Use the exact-event workflow
described below to copy a pending event.

Monitor structured records with `metric_name=v1_household_mirror_operations`.
A successful copy's message is `V1 household immediate copy completed`, and a
failed copy's is `V1 household immediate copy failed`, at ERROR.
Alert on `outcome=error`, grouped by `failure_category` and `country_id`, and
inspect `pending_event`. The copy service logs each record with the legacy
identifier, destination UUID when available, configured and actual database
sources, duration, and outcome; it logs no household values, SQL, database
URLs, or credentials. The observability runtime then drops attributes whose
keys contain `household` or `person` and attributes whose values are null or
not single values, so in the log bucket a record has no `legacy_household_id`,
`destination_household_id`, `household_created`, `attempted_write_sources` or
`actual_write_sources`, nor `mapping_created` when it is null, and
`attributes.omitted_count` counts what was dropped.

A failed copy also records the exception's class name in `error_type`, and a
`translation` failure records a fixed `failure_reason`. For other categories
`failure_reason` is null, so the log bucket's record has none. The record
never holds the error's message, which can quote the household's names.

These are the reasons a copy can record. A translation whose result breaks a
v2 household document rule records that rule's reason:

| Source | `failure_reason` |
| --- | --- |
| The v1 household | `legacy_unsupported_collections` (a top-level key other than `people`, the country's group collections and, for the US, `spm`), `legacy_people_not_object`, `legacy_groups_not_object`, `legacy_group_not_object`, `legacy_members_not_named_people`, `legacy_person_in_multiple_groups`, `legacy_person_not_object`, `legacy_ambiguous_default_year` (values without periods and no single year the others give), `legacy_default_year_out_of_range` (the year the periods give is outside the years v2 accepts), `legacy_period_invalid` (a period key whose dates can't be computed, such as `day:9999-12-31:2`), `value_not_json` (values nested deeper than the v2 document allows) |
| The translated v2 document | `incomplete_memberships` (a person in no record of one of the country's entity collections), `invalid_identifier` (a person or group name that is blank or longer than 255 characters), `too_many_records`, `too_many_values`, `spm_not_object`, `spm_selection_invalid` |

The other `HouseholdValidationReason` codes name rules that the translation's
own output always meets, such as `duplicate_record_id` or
`absent_membership_target`; they apply to documents sent to the v2 household
routes, not to copies. A v1 household holding a value that isn't
standards-compliant JSON in other ways, such as a number that isn't finite, is
not saved at all while dual-write is on: recording its copy event validates the
snapshot, so the v1 save fails and no copy is attempted.

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
command connects through it as `policyengine_schema_migrator`. The workflow
installs the runtime dependencies from `uv.lock` (`uv sync --frozen`), and the
script runs the command through `uv run --frozen`, so a local run needs uv and
uses the same locked versions. The corresponding local command is intended only
for an already authenticated operator with the same explicit settings and an
active staging-only proxy:

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

The ordinary staging candidate tests, focused household tests, disposable
MySQL/PostgreSQL cross-database tests, and manually dispatched exact-event
operation remain. Production jobs depend on successful promotion of the tested
staging candidate rather than a separate Stage 10 or Stage 11 exercise.

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
mirror event. A failed copy does not fail a create under `dual_write`, so copy
failures on their own are handled from the `outcome=error` records and the
exact-event workflow, not by rolling back. Application revisions built before
that change return HTTP 503 for a failed copy; do not route traffic to one
whose environment selects `DB_WRITE_HOUSEHOLD=dual_write`. Leave
`DB_READ_HOUSEHOLD=cloud_sql` and
`ROUTE_IMPL_HOUSEHOLD=flask_fallback`. Do not delete previously committed v2
households, mappings, associations, or source events. Application rollback
does not automatically downgrade either schema; any schema downgrade requires
a separate approval and proof that retained data no longer depends on it.

The recorded staging qualification supported the initial Stage 11 review.
Apply the reviewed schema revisions and application image only to independently
verified production targets. Enable native v2 use and v1 create copying as
separate operational decisions and retain the preceding application revision
for immediate rollback.

## Removal of Canada, Nigeria and Israel

The Public API no longer serves Canada, Nigeria and Israel, and their country
packages are no longer installed. Their v1 household requests are rejected as
unknown countries before any write, so the Cloud SQL-only path described
above for those countries no longer runs. Existing Cloud SQL rows for them
are kept.

## Household Calculations

`POST /v2/household-calculations` calculates a household stored through
`/v2/households`, under a policy stored through `/v2/policies` or under
current law, on the simulation service's v2 household functions. It needs no
account. The body names `country_id`, `household_id`, an optional
`policy_id`, optional `axes` (at most 8 groups of at most 32 axes, one point
count per group, at most 10,000 points in all), `add_missing_variables` and
optional `spm` settings. The year calculated is the household's
`default_year`. Before anything is sent, the Public API checks, in order:

1. that the country's `countries` row has `household_enabled` (422 otherwise);
2. that the household, and the policy when one is named, exist in that
   country (404 otherwise);
3. that the household has a `default_year` (422 otherwise);
4. that the policy sets no parameter the running catalog version lacks (422
   with `code` `missing_parameters` and the parameters' names in
   `missing_parameters`). A policy no published catalog of the running
   PolicyEngine.py version can check passes.

It then sends the simulation service's `POST /household-calculations` the
IDs and options, with the request's ID and observability ID headers. The
answer is 202 with the new job's `calculation_id` and `status`; each
submission creates a new job. The simulation service's 422 reasons reach the
caller as 422. A 202 whose body the Public API can't read is 502, since the
job exists. So is a 500 from the simulation service (`internal_error`), an
answer lost after the submission may have been sent (a read timeout or a
dropped connection), and a 502 or 504 a proxy in front of the simulation
service answered in its place, since each may come after it created the job.
No route finds a household job without its ID, so the 502's message asks the
caller to submit the household calculation again, and says that this
creates a second job if the first request went through; in parentheses it
names what happened (the transport error, the proxy's status, the simulation
service's 500 code and reason, or the unreadable 202). Any other refusal
(with the simulation service's `code` and reason in the message, and the
failed job's ID when Modal refused the call), a connection never made, a
refusal the Public API can't read, missing configuration or a gateway token
it can't fetch is 503. A failed catalog query in the policy check is 503 too. Every
answer given once the call was attempted carries
`X-PolicyEngine-Observability-Id` with the attempt's ID, which the
simulation service never received after a connection never made or a token
that couldn't be fetched; a refusal before the attempt carries none, not even
the caller's.

`GET /v2/household-calculations/{calculation_id}` reads the job from
`household_jobs`, which the simulation service inserts and its household
function completes, as the runtime role, and never calls the simulation
service. It answers the job's status, catalog and package versions and
times; once it succeeded, `result` (the calculated household in its stored
key order, its warnings, the SPM selection applied and the SPM receipt);
once it failed, `error` (the household function's error code and message,
with the inputs it doesn't recognize and its SPM error, or only the job's
error message when it failed without one). An unknown ID is 404, and a
succeeded job whose result can't be read is 500.

The call to the simulation service goes through
`policyengine_api/libs/simulation_household_calculations.py`, at
`SIMULATION_ENTRYPOINT_URL` with the gateway credentials of every other
simulation call. `post_household_calculation` is the only code that sends
the request, so moving to the generated simulation client changes that
function and the dependency.

The live staging job runs, after the other live tests: a submit and read
cycle, six calculations submitted at once (each accepted within
`STAGING_HOUSEHOLD_SUBMIT_LIMIT_SECONDS`, 10 by default, and finished within
`STAGING_HOUSEHOLD_FINISH_LIMIT_SECONDS`, 300), a household across 401 axis
points, and a parity set of three US and three UK households compared value
by value with `/calculate` and `/calculate-full`. The checks need the
simulation service's household calculation route deployed to staging first.
