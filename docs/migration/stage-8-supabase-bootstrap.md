# Stage 8 Supabase migration and Storage bootstrap

This runbook operates only on the approved dormant API v2-alpha target. It is
not application startup logic. Cloud SQL and all existing production routes and
compute remain primary throughout Stage 8.

Concrete organization, project, region, endpoint, bucket, credential, and
secret-resource identifiers are intentionally excluded. Resolve them from the
approved environment configuration and secret-management surfaces.

## Required identity and credential boundaries

The operator must resolve and validate all of the following without copying
their values into this repository:

- `V2_SUPABASE_ENVIRONMENT`
- `V2_SUPABASE_PROJECT_REF`
- `V2_SUPABASE_STORAGE_URL`
- `V2_SUPABASE_STORAGE_BUCKET`

Inject the database migration password and Storage administration key from
their separate approved secrets at execution time. Do not echo them, place them
in repository files, reuse the migration URL as runtime configuration, or
expose the Storage key to the application service account.

## Ordered explicit operations

1. Confirm the separately maintained target inventory and its successful
   freshness audit. Stop on any identity ambiguity or unexpected application
   state; never reset, adopt, or stamp the database.
2. Supply `V2_MIGRATION_DATABASE_URL`, `V2_SUPABASE_ENVIRONMENT`, and
   `V2_SUPABASE_PROJECT_REF` to an explicit operator or CI migration step.
3. Run `uv run alembic -c alembic-v2.ini upgrade head`, followed by
   `uv run alembic -c alembic-v2.ini check`. The v2 chain requires an online
   connection so it can qualify the persistent target and verify generated
   application-data before/after states.
4. Remove the migration credential from the execution environment. Supply the
   separate `V2_SUPABASE_STORAGE_ADMIN_KEY` together with the validated
   `V2_SUPABASE_STORAGE_URL`, `V2_SUPABASE_STORAGE_BUCKET`,
   `V2_SUPABASE_PROJECT_REF`, and `V2_SUPABASE_ENVIRONMENT` values.
5. Run `uv run python3 scripts/bootstrap_v2_supabase_storage.py`. A fresh run
   creates the reviewed private bucket. A repeat run verifies it and reports
   `created: false`. An incompatible existing bucket stops without update,
   deletion, recreation, or public exposure.
6. Remove the Storage administration credential from the execution environment
   and run `uv run python3 scripts/check_stage8_scaffolding_hygiene.py` before
   commit.

The Storage initializer calls only Supabase's bucket-management endpoint. It
does not run Alembic, import application startup, modify application tables or
rows, initialize canonical metadata, upload an object, or create an access
policy. The dedicated server-side Storage administration key is sent only in
the `apikey` header; it is not a JWT and must not be placed in
`Authorization: Bearer`. The initializer recognizes both structured current
Storage errors such as `NoSuchBucket` and legacy HTTP 404/409 responses without
logging response bodies.

Supabase documents that buckets are private by default and that bucket creation
needs bucket insert permission but no object permission:
<https://supabase.com/docs/guides/storage/buckets/fundamentals> and
<https://supabase.com/docs/reference/javascript/file-buckets-createbucket>.
The current key and Storage error contracts are documented at
<https://supabase.com/docs/guides/getting-started/migrating-to-new-api-keys>
and <https://supabase.com/docs/guides/storage/debugging/error-codes>.

## Repository hygiene

One-off SQL, dumps, generated payloads, temporary environment files, Supabase
CLI state, scratch scaffolding, target identifiers, and secret-resource names
belong only in approved ignored local-artifact or system-temporary locations
and must be removed after use. If an operation is needed again, promote it to
tested idempotent tooling before committing it. Generated Alembic revisions,
declarative migration sources, this supported initializer, tests, and sanitized
durable documentation are reviewed project artifacts, not disposable
scaffolding.
